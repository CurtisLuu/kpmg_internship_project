import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import { msalInstance } from './msalConfig';

// MSAL v3 requires initialize() before use; render only after it completes to avoid uninitialized errors
msalInstance.initialize().then(() => {
  const root = ReactDOM.createRoot(document.getElementById('root'));
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
});
