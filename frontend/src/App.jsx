import { useState, useEffect } from 'react'
import axios from 'axios'

function App() {
  const [status, setStatus] = useState('загрузка…')
  const [queue, setQueue]   = useState('–')

  useEffect(() => {
    // 1) статус сервиса
    axios.get(`${window.APP_CONFIG.apiBaseUrl}/health`)
      .then(res => setStatus(res.data.status))
      .catch(() => setStatus('ошибка запроса'))

    // 2) длина очереди
    axios.get(`${window.APP_CONFIG.apiBaseUrl}/queue_length`)
      .then(res => setQueue(res.data.queue_length))
      .catch(() => setQueue('ошибка запроса'))
  }, [])

  return (
    <div className="App" style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
      <h1>Статус сервиса: {status}</h1>
      <h2>Длина очереди: {queue}</h2>
    </div>
  )
}

export default App

