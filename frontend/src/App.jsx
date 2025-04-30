import { useState, useEffect } from 'react'
import './App.css'

function App() {
  const [status, setStatus] = useState('loading')
  const [queueLength, setQueueLength] = useState(null)

  // 1) URL API берём из внешней конфигурации
  const apiBase = window.APP_CONFIG?.apiBaseUrl || ''

  useEffect(() => {
    // 2) Запрос статуса
    fetch(`${apiBase}/health`)
      .then(res => res.json())
      .then(json => setStatus(json.status))
      .catch(() => setStatus('error'))

    // 3) Запрос длины очереди
    fetch(`${apiBase}/queue_length`)
      .then(res => res.json())
      .then(json => setQueueLength(json.queue_length))
      .catch(() => setQueueLength('error'))
  }, [apiBase])

  return (
    <div className="App">
      <h1>Статус сервиса</h1>
      <p><strong>Статус сервиса:</strong> {status}</p>
      <p><strong>Длина очереди:</strong> {queueLength}</p>
    </div>
  )
}

export default App
