/// <reference types="vite/client" />

// 这一行以前不存在。TS 5 对 `import './styles.css'` 这类副作用导入是放行的
// （宽松解析），所以问题一直没暴露；TypeScript 7（原生端口）把它收紧成
// TS2882「找不到模块或类型声明」，于是 main.tsx 的两行 CSS 导入直接编译失败。
//
// 正确的修法不是关掉检查，而是补上本来就该有的 Vite 客户端类型声明 ——
// 它声明了 *.css / *.svg / import.meta.env 等 Vite 特有的模块形态。
// 本文件被 tsconfig 的 include: ["src", ...] 覆盖，无需额外配置 types 字段。
export {}
