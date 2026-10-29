import { fileURLToPath } from 'node:url'
import { defineConfig } from 'wxt'

// 확장이 부르는 분석 서버. 배포한 서버로 빌드하려면 WXT_API_BASE에 주소를 준다.
// WXT가 .env를 config 평가 뒤에 읽으므로 manifest·vite 함수 안에서 읽는다.
function apiBase() {
  const url = new URL(process.env.WXT_API_BASE || 'http://localhost:8000')
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error(`WXT_API_BASE는 http(s) 주소여야 한다: ${url.href}`)
  return url
}

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  manifest: () => {
    const api = apiBase()
    return {
      name: '장단',
      description: '선택한 글에서 길게 읽을 음절을 표시합니다.',
      // 아이콘을 누른 탭에서만 선택한 글을 읽는다. 서버 주소 권한이 있으면 확장 페이지의 요청은 CORS를 받지 않는다.
      permissions: ['activeTab', 'scripting'],
      host_permissions: [`${api.protocol}//${api.hostname}/*`],
    }
  },
  vite: () => ({
    define: { __API_BASE__: JSON.stringify(apiBase().origin) },
    resolve: { dedupe: ['react', 'react-dom'] }, // ../web/src 컴포넌트도 이 폴더의 React를 쓴다
    server: { fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] } },
  }),
})
