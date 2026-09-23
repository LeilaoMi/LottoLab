"""Walk-forward comparison with frozen datasets and recorded fit boundaries."""

import importlib.metadata
from decimal import Decimal

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .analysis import adjust_pvalues
from .domain import Rule, dlt_fixed_amount, dlt_prize_tier_for, ssq_prize_tier
from .features import FEATURE_NAMES, FEATURE_VERSION, causal_features, choose_top, coherent_marginals
from .provenance import code_fingerprint
from .schemas import BacktestRequest

MODEL_CATALOG = [
    {
        "id": "uniform",
        "name": "均匀随机",
        "description": "每号使用理论入选概率；随机打破排名并列。",
        "family": "理论基线",
    },
    {
        "id": "frequency",
        "name": "历史频率",
        "description": "仅使用之前最多 100 期，加入均匀先验平滑。",
        "family": "经验基线",
    },
    {
        "id": "logistic",
        "name": "逻辑回归",
        "description": "训练窗口内拟合标准化与线性二分类，再做基数一致性投影。",
        "family": "线性模型",
    },
    {
        "id": "gradient_boosting",
        "name": "梯度提升树",
        "description": "浅层直方图提升树；固定参数，关闭随机内部验证切分。",
        "family": "树模型",
    },
]


def new_estimator(model_id: str, seed: int):
    if model_id == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.2, max_iter=300, random_state=seed))
    return HistGradientBoostingClassifier(
        max_iter=60,
        max_leaf_nodes=7,
        learning_rate=0.06,
        l2_regularization=5,
        min_samples_leaf=40,
        early_stopping=False,
        random_state=seed,
    )


def binary_metrics(probabilities, labels):
    p = np.clip(probabilities, 1e-9, 1 - 1e-9)
    return float(np.mean((p - labels) ** 2)), float(
        -np.mean(labels * np.log(p) + (1 - labels) * np.log1p(-p))
    )


def settle_reward(
    rule_code: str, dataset_kind: str, actual: dict, main_hits: int, special_hits: int
) -> tuple[Decimal | None, bool]:
    """单注单期结算 → (金额或 None, 是否已结算)。

    SSQ/DLT 真实数据：当期奖金表优先；DLT 固定奖级按规则版本常量回退；
    未中按 0 结算；浮动奖无当期数据则未结算（不猜）。口径均为基本投注、税前。
    """
    if dataset_kind != "real" or rule_code not in ("ssq", "dlt"):
        return None, False
    if rule_code == "ssq":
        tier = ssq_prize_tier(main_hits, special_hits)
    else:
        tier = dlt_prize_tier_for(actual.get("draw_date") or actual.get("date"), main_hits, special_hits)
    if not tier:
        return Decimal(0), True
    payout = (actual.get("prizes") or {}).get(tier)
    if payout is not None and Decimal(str(payout)) > 0:
        return Decimal(str(payout)), True
    if payout is not None:
        return None, False
    if rule_code == "dlt":
        fixed = dlt_fixed_amount(tier, actual.get("draw_date") or actual.get("date"))
        if fixed is not None:
            return Decimal(fixed), True
    return None, False


def half_split_stability(differences: np.ndarray) -> dict:
    """测试窗前后半的平均优势对照（纯描述性，不做检验、不参与 verdict）。

    两半同号记 CONSISTENT，否则 INCONSISTENT；半窗不足 10 期记 TOO_SHORT。
    新增切分维度会扩大事后挑选空间，本字段只描述稳定性，不做任何决策依据。
    """
    n = len(differences)
    if n < 20:
        return {"verdict": "TOO_SHORT", "first_half": None, "second_half": None, "n": n}
    cut = n // 2
    first = float(np.mean(differences[:cut]))
    second = float(np.mean(differences[cut:]))
    same_sign = (first > 0 and second > 0) or (first < 0 and second < 0)
    return {
        "verdict": "CONSISTENT" if same_sign else "INCONSISTENT",
        "first_half": first,
        "second_half": second,
        "n": n,
    }


def block_comparison(differences: np.ndarray, seed: int, samples: int) -> dict:
    size = len(differences)
    mean = float(np.mean(differences))
    if np.std(differences) < 1e-12:
        return {
            "delta": mean,
            "confidence_interval": [mean, mean],
            "p_value": 1.0 if abs(mean) < 1e-12 else 1 / (samples + 1),
            "effect_size": None,
            "block_length": 1,
        }
    rng = np.random.default_rng(seed)
    block = max(2, min(20, int(np.ceil(np.sqrt(size)))))
    starts = rng.integers(0, size, size=(samples, int(np.ceil(size / block))))
    indices = ((starts[:, :, None] + np.arange(block)) % size).reshape(samples, -1)[:, :size]
    resampled = differences[indices].mean(axis=1)
    centered_null = resampled - mean
    p_value = (1 + int(np.sum(np.abs(centered_null) >= abs(mean)))) / (samples + 1)
    return {
        "delta": mean,
        "confidence_interval": np.quantile(resampled, [0.025, 0.975]).tolist(),
        "p_value": p_value,
        "effect_size": mean / float(np.std(differences, ddof=1)),
        "block_length": block,
    }


def run_backtest(
    draws: list[dict], rule: Rule, config: BacktestRequest, progress=lambda _value: None
) -> dict:
    start = len(draws) - config.test_draws
    if start < 80:
        raise ValueError("训练期不足：测试区间之前至少需要 80 期")
    fingerprint = code_fingerprint()
    main_x, main_y = causal_features(draws, rule, "main")
    special_x, special_y = causal_features(draws, rule, "special")
    model_results: list[dict] = []
    fit_events = []
    all_records: dict[str, list] = {}
    for model_index, model_id in enumerate(config.models):
        seed_offset = next(i for i, model in enumerate(MODEL_CATALOG) if model["id"] == model_id)
        rng = np.random.default_rng(config.seed + seed_offset * 1009)
        records = []
        main_estimator = special_estimator = None
        cost = Decimal(rule.ticket_price) * config.test_draws
        gross = Decimal(0)
        missing_settlements = 0
        with threadpool_limits(limits=1):
            for t in range(start, len(draws)):
                train_start = max(0, t - config.training_window)
                if model_id in ("logistic", "gradient_boosting") and (
                    main_estimator is None or (t - start) % config.retrain_every == 0
                ):
                    main_estimator = new_estimator(model_id, config.seed)
                    main_estimator.fit(
                        main_x[train_start:t].reshape(-1, len(FEATURE_NAMES)), main_y[train_start:t].ravel()
                    )
                    if rule.special_count:
                        special_estimator = new_estimator(model_id, config.seed)
                        special_estimator.fit(
                            special_x[train_start:t].reshape(-1, len(FEATURE_NAMES)),
                            special_y[train_start:t].ravel(),
                        )
                    fit_events.append(
                        {
                            "model": model_id,
                            "train_start_issue": draws[train_start]["issue"],
                            "train_end_issue": draws[t - 1]["issue"],
                            "predict_from_issue": draws[t]["issue"],
                            "train_start_index": train_start,
                            "train_end_exclusive": t,
                        }
                    )
                if model_id == "uniform":
                    main_p = np.full(rule.main_max, rule.main_count / rule.main_max)
                elif model_id == "frequency":
                    begin = max(0, t - min(100, config.training_window))
                    main_p = (main_y[begin:t].sum(axis=0) + 2 * rule.main_count / rule.main_max) / (
                        t - begin + 2
                    )
                else:
                    assert main_estimator is not None
                    main_p = coherent_marginals(
                        main_estimator.predict_proba(main_x[t])[:, 1], rule.main_count
                    )
                # 快乐8 规则 main_count=20 是开奖球数；可售票面为 1..10（与推荐 PICK 一致）
                ticket_k = 10 if rule.code == "kl8" else rule.main_count
                main_ticket = choose_top(main_p, ticket_k, rng)
                actual = draws[t]
                main_hits = len(set(main_ticket) & set(actual["main_numbers"]))
                main_brier, main_loss = binary_metrics(main_p, main_y[t])
                if rule.special_count:
                    if model_id == "uniform":
                        special_p = np.full(rule.special_max, rule.special_count / rule.special_max)
                    elif model_id == "frequency":
                        begin = max(0, t - min(100, config.training_window))
                        special_p = (
                            special_y[begin:t].sum(axis=0) + 2 * rule.special_count / rule.special_max
                        ) / (t - begin + 2)
                    else:
                        assert special_estimator is not None
                        special_p = coherent_marginals(
                            special_estimator.predict_proba(special_x[t])[:, 1], rule.special_count
                        )
                    special_ticket = choose_top(special_p, rule.special_count, rng)
                    special_hits = len(set(special_ticket) & set(actual["special_numbers"]))
                    special_brier, special_loss = binary_metrics(special_p, special_y[t])
                else:
                    special_p = np.zeros(0)
                    special_ticket = []
                    special_hits = 0
                    special_brier, special_loss = 0.0, 0.0
                reward, settled = settle_reward(
                    rule.code, config.dataset_kind, actual, main_hits, special_hits
                )
                if settled:
                    gross += reward or Decimal(0)
                else:
                    missing_settlements += 1
                records.append(
                    {
                        "issue": actual["issue"],
                        "date": actual["draw_date"],
                        "main_ticket": main_ticket,
                        "special_ticket": special_ticket,
                        "main_hits": main_hits,
                        "special_hits": special_hits,
                        "main_brier": main_brier,
                        "main_log_loss": main_loss,
                        "special_brier": special_brier,
                        "special_log_loss": special_loss,
                        "main_probabilities": main_p.tolist(),
                        "special_probabilities": special_p.tolist(),
                        "reward": str(reward) if reward is not None else None,
                    }
                )
                if (t - start) % 10 == 0:
                    progress(int(95 * (model_index + (t - start) / config.test_draws) / len(config.models)))
        all_records[model_id] = records
        metrics = {
            key: float(np.mean([row[key] for row in records]))
            for key in (
                "main_brier",
                "main_log_loss",
                "special_brier",
                "special_log_loss",
                "main_hits",
                "special_hits",
            )
        }
        ticket_k = 10 if rule.code == "kl8" else rule.main_count
        metrics["precision_at_k"] = metrics["main_hits"] / ticket_k
        metrics["recall_at_k"] = metrics["main_hits"] / rule.main_count
        metrics["special_exact_hit_rate"] = float(
            np.mean([row["special_hits"] == rule.special_count for row in records])
        )
        calibration = []
        probabilities = np.asarray([row["main_probabilities"] for row in records]).ravel()
        labels = main_y[start:].ravel()
        bin_ids = np.minimum(9, np.floor(probabilities * 10).astype(int))
        for bin_id in range(10):
            mask = bin_ids == bin_id
            if mask.any():
                calibration.append(
                    {
                        "predicted": float(probabilities[mask].mean()),
                        "observed": float(labels[mask].mean()),
                        "count": int(mask.sum()),
                    }
                )
        model_results.append(
            {
                "model": model_id,
                "name": next(m["name"] for m in MODEL_CATALOG if m["id"] == model_id),
                "metrics": metrics,
                "calibration": calibration,
                "cost": str(cost),
                "gross": str(gross) if not missing_settlements else None,
                "roi": float((gross - cost) / cost) if not missing_settlements else None,
                "missing_settlements": missing_settlements,
                "verdict": "BASELINE",
            }
        )
    baseline = np.asarray([row["main_brier"] for row in all_records["uniform"]])
    comparisons: list[dict] = []
    for model in model_results:
        if model["model"] == "uniform":
            model["comparison"] = None
            model["stability"] = None
            continue
        values = baseline - np.asarray([row["main_brier"] for row in all_records[model["model"]]])
        model["comparison"] = block_comparison(values, config.seed, config.bootstrap_samples)
        model["stability"] = half_split_stability(values)
        comparisons.append(model)
    adjusted = adjust_pvalues([model["comparison"]["p_value"] for model in comparisons])
    for model, p_value in zip(comparisons, adjusted, strict=True):
        comparison = model["comparison"]
        comparison["adjusted_p_value"] = p_value
        ci = comparison["confidence_interval"]
        model["verdict"] = (
            "SIGNIFICANT"
            if comparison["delta"] > 0 and ci[0] > 0 and p_value < 0.05
            else "WORSE_THAN_BASELINE"
            if comparison["delta"] < 0 and ci[1] < 0 and p_value < 0.05
            else "NOT_SIGNIFICANT"
        )
    return {
        "config": config.model_dump(mode="json"),
        "sample_size": config.test_draws,
        "start_issue": draws[start]["issue"],
        "end_issue": draws[-1]["issue"],
        "train_first_issue": draws[max(0, start - config.training_window)]["issue"],
        "models": model_results,
        "records": all_records,
        "fit_events": fit_events,
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "code_fingerprint": fingerprint,
        "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "scikit-learn")},
        "primary_metric": "主区逐号码平均二元 Brier；优势 = 随机基线 Brier − 模型 Brier",
        "comparison_method": "按期开奖配对的循环移动块 bootstrap，中心化零假设，双侧 p 值；本次模型比较做 Bonferroni 校正",
        "stability_method": "测试窗前后半平均优势对照，仅描述稳定性，不做检验、不参与 verdict",
        "limitations": [
            "95% 区间是名义区间，块 bootstrap 依赖局部平稳近似，不代表未来保证。",
            "超参数固定；没有使用测试区间调参，重复尝试不同配置仍需跨实验校正。",
            "前后半对照只描述稳定性，不做显著性检验也不参与 verdict；新增切分维度会扩大事后挑选空间，跨实验解释仍需校正。",
            "基数一致性投影不是样本外概率校准的证明；校准图仅用于检验。",
            "收益只按 SSQ/DLT 历史奖金税前结算（基本投注口径，不含追加与派奖，不重算新增投注对分奖的影响）："
            "当期奖金表优先，DLT 固定奖按规则版本常量回退（2019-02-20 第19019期为界），"
            "浮动奖缺数则该期不计入；缺失派奖或演示数据不输出 ROI。",
        ],
    }
