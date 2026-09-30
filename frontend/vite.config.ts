import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    rollupOptions: {
      output: {
        // Vite 8（Rolldown）把 manualChunks 的对象形式去掉了，只接受函数形式。
        // 旧写法 `manualChunks: { charts: ['recharts'] }` 在 Vite 8 下类型报错：
        //   'charts' does not exist in type 'ManualChunksFunction'
        // 语义等价：把 recharts 及其依赖归到 charts 这一个 chunk。
        manualChunks(id) {
          if (
            id.includes('recharts') ||
            id.includes('node_modules/d3-') ||
            id.includes('node_modules/internmap')
          ) {
            return 'charts'
          }
          return undefined
        },
      },
    },
  },
})
