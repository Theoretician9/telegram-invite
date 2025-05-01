// frontend/src/Logs.jsx
import React, { useEffect, useState, useRef } from 'react'
import axios from 'axios'

export default function Logs() {
  const [lines, setLines] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)

  const fetchLogs = () => {
    setLoading(true)
    axios.get('/api/logs')
      .then(({ data }) => {
        // разбиваем на строки и берём последние 50
        const allLines = data.split('\n')
        setLines(allLines.slice(-50))
        setError(null)
      })
      .catch(() => {
        setError('Не удалось загрузить логи')
      })
      .finally(() => {
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchLogs()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div style={{ padding: 20, fontFamily: 'sans-serif' }}>
      <h1>Логи приглашений</h1>
      <button onClick={fetchLogs} disabled={loading}>
        {loading ? 'Загрузка…' : 'Обновить'}
      </button>
      {error && <p style={{ color: 'red' }}>{error}</p>}
<pre style={{
  background: '#f0f0f0',
  color: '#000',          // текст чёрный
  padding: 10,
  maxHeight: '70vh',
  overflowY: 'auto',
  marginTop: 10,
  whiteSpace: 'pre-wrap', // чтобы длинные строки переносились
  wordBreak: 'break-all'
}}>
  {lines.map((l, i) => <div key={i}>{l}</div>)}
  <div ref={bottomRef} />
</pre>
    </div>
  )
}
