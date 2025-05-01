// frontend/src/App.jsx

import React from 'react'
import { NavLink, Routes, Route } from 'react-router-dom'
import Stats from './Stats'
import Logs from './Logs'
import Accounts from './Accounts'

export default function App() {
  return (
    <div style={{ fontFamily: 'sans-serif' }}>
      <nav style={{ padding: 20, borderBottom: '1px solid #ccc' }}>
        <NavLink
          to="/"
          end
          style={({ isActive }) => ({
            marginRight: 20,
            textDecoration: 'none',
            fontWeight: isActive ? 'bold' : 'normal'
          })}
        >
          Статистика
        </NavLink>

        <NavLink
          to="/logs"
          style={({ isActive }) => ({
            marginRight: 20,
            textDecoration: 'none',
            fontWeight: isActive ? 'bold' : 'normal'
          })}
        >
          Логи
        </NavLink>

        <NavLink
          to="/accounts"
          style={({ isActive }) => ({
            textDecoration: 'none',
            fontWeight: isActive ? 'bold' : 'normal'
          })}
        >
          Аккаунты
        </NavLink>
      </nav>

      <Routes>
        <Route path="/" element={<Stats />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/accounts" element={<Accounts />} />
      </Routes>
    </div>
  )
}
