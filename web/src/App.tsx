import './App.css'

function App() {
  return (
    <main className="app-container">
      <header className="app-header">
        <h1>PBL4 Distributed Training Dashboard</h1>
        <p className="status-badge">Bootstrap Scaffold</p>
      </header>
      <section className="app-content">
        <p>
          WebUI interface scaffold. Connects to the Backend management API and WebSocket
          for monitoring distributed attempts and parameter synchronization.
        </p>
      </section>
    </main>
  )
}

export default App
