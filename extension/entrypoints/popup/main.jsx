import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import '../../../web/src/app.css'
import './popup.css'

// 웹 글꼴은 스크립트로 붙인다. HTML에 둔 원격 스타일시트는 받을 때까지 스크립트 실행을 막아, 망이 느리면 팝업이 비어 보인다.
const fonts = document.createElement('link')
fonts.rel = 'stylesheet'
fonts.href =
  'https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;500;600&display=swap'
document.head.append(fonts)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
