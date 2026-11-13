import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { ServicesProvider } from './lib/services'
import './styles.css'

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <ServicesProvider>
      <App />
    </ServicesProvider>
  </StrictMode>
)
