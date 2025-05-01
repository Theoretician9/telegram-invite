// frontend/src/StatsChart.jsx

import React, { useEffect, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip
} from 'recharts'
import axios from 'axios'

export default function StatsChart() {
  const [period, setPeriod] = useState('day')
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    axios.get(`/api/stats/history?period=${period}`)
      .then(({ data }) => {
        setData(data)
        setError(null)
      })
      .catch(() => setError('Ошибка загрузки тренда'))
      .finally(() => setLoading(false))
  }, [period])

  if (loading) return <p>Загрузка графика…</p>
  if (error)   return <p style={{ color: 'red' }}>{error}</p>

  return (
    <div style={{ width: '100%', height: 300, marginTop: 20 }}>
      <div style={{ marginBottom: 10 }}>
        <button onClick={() => setPeriod('day')} disabled={period === 'day'}>
          Сутки
        </button>
        <button
          onClick={() => setPeriod('week')}
          disabled={period === 'week'}
          style={{ marginLeft: 10 }}
        >
          Неделя
        </button>
      </div>
      <ResponsiveContainer>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="timestamp" />
          <YAxis allowDecimals={false} />
          <Tooltip />
          <Line type="monotone" dataKey="count" stroke="#8884d8" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
