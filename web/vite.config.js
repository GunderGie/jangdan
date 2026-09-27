import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 중에는 API(uvicorn, 8000번)로 넘긴다. 빌드 결과(dist)는 FastAPI가 같은 주소에서 내보낸다.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
