// frontend/src/App.jsx

import { useEffect, useState } from 'react'
import axios from 'axios'

export default function App() {
  const [stats, setStats] = useState({
    invited: 0,
    link_sent: 0,
    failed: 0,
    skipped: 0,
    queue_length: 0,
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let isMounted = true

    const fetchStats = () => {
      axios.get('/api/stats')
        .then(({ data }) => {
          if (!isMounted) return
          setStats(data)
          setError(null)
        })
        .catch(err => {
          console.error(err)
          if (isMounted) setError('Ошибка при загрузке статистики')
        })
        .finally(() => {
          if (isMounted) setLoading(false)
        })
    }

    // первый вызов сразу при монтировании
    fetchStats()
    // повторять каждые 5 секунд
    const intervalId = setInterval(fetchStats, 5000)

    return () => {
      isMounted = false
      clearInterval(intervalId)
    }
  }, [])

  if (loading) return <p>Загрузка...</p>
  if (error) return <p style={{ color: 'red' }}>{error}</p>

  return (
    <div style={{ padding: 20, fontFamily: 'sans-serif' }}>
      <h1>Панель приглашений</h1>
      <ul>
        <li><strong>Приглашено:</strong> {stats.invited}</li>
        <li><strong>Отправлено ссылок:</strong> {stats.link_sent}</li>
        <li><strong>Ошибок:</strong> {stats.failed}</li>
        <li><strong>Пропущено:</strong> {stats.skipped}</li>
        <li><strong>Длина очереди:</strong> {stats.queue_length}</li>
      </ul>
    </div>
  )
}
