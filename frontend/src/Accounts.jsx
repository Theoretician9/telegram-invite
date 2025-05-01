// frontend/src/Accounts.jsx
import React, { useEffect, useState } from 'react'
import axios from 'axios'

export default function Accounts() {
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    axios.get('/api/accounts')
      .then(({ data }) => {
        setAccounts(data)
        setError(null)
      })
      .catch(() => {
        setError('Не удалось загрузить список аккаунтов')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  if (loading) return <p>Загрузка...</p>
  if (error) return <p style={{ color: 'red' }}>{error}</p>

  return (
    <div style={{ padding: 20, fontFamily: 'sans-serif' }}>
      <h1>Аккаунты</h1>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ borderBottom: '1px solid #ccc', textAlign: 'left', padding: '8px' }}>Имя</th>
            <th style={{ borderBottom: '1px solid #ccc', textAlign: 'left', padding: '8px' }}>Последнее использование</th>
            <th style={{ borderBottom: '1px solid #ccc', textAlign: 'left', padding: '8px' }}>Осталось приглашений</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((acc, idx) => (
            <tr key={idx}>
              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>{acc.name}</td>
              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                {acc.last_used ? new Date(acc.last_used).toLocaleString() : '-'}
              </td>
              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                {acc.invites_left}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
