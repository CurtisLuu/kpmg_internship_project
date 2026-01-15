import React, { useEffect, useState, createContext, useContext } from 'react';
import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { InteractionRequiredAuthError } from "@azure/msal-browser";

// Create context for bypass auth state
const BypassAuthContext = createContext();

export const useBypassAuth = () => useContext(BypassAuthContext);

const AuthenticationComponent = ({ children }) => {
  const { instance, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [bypassAuth, setBypassAuth] = useState(false);

  useEffect(() => {
    // Check if user is already logged in
    instance.handleRedirectPromise()
      .then(() => {
        setLoading(false);
      })
      .catch((error) => {
        console.error("Error during redirect handling:", error);
        setError("Authentication error occurred");
        setLoading(false);
      });
  }, [instance]);

  const handleLogin = async () => {
    try {
      setLoading(true);
      setError(null);
      await instance.loginPopup({
        scopes: ["openid", "profile", "email"],
      });
    } catch (error) {
      console.error("Login error:", error);
      setError("Failed to login. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      setLoading(true);
      await instance.logout({
        postLogoutRedirectUri: "/",
      });
    } catch (error) {
      console.error("Logout error:", error);
      setError("Failed to logout. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const getAccessToken = async () => {
    try {
      const response = await instance.acquireTokenSilent({
        scopes: ["openid", "profile", "email"],
        account: accounts[0],
      });
      return response.accessToken;
    } catch (error) {
      if (error instanceof InteractionRequiredAuthError) {
        const response = await instance.acquireTokenPopup({
          scopes: ["openid", "profile", "email"],
        });
        return response.accessToken;
      }
      throw error;
    }
  };

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        fontSize: '18px',
        color: '#666'
      }}>
        Loading...
      </div>
    );
  }

  if (!isAuthenticated && !bypassAuth) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        backgroundColor: '#f5f5f5',
        gap: '20px'
      }}>
        <div style={{
          textAlign: 'center',
          padding: '60px 40px',
          backgroundColor: 'white',
          borderRadius: '12px',
          boxShadow: '0 4px 16px rgba(0, 0, 0, 0.12)',
          minWidth: '420px',
          maxWidth: '500px'
        }}>
          <img 
            src="/kpmg_logo.png" 
            alt="KPMG" 
            style={{ 
              height: '60px', 
              marginBottom: '24px',
              objectFit: 'contain'
            }} 
          />
          <h1 style={{ marginBottom: '16px', color: '#333', fontSize: '28px', fontWeight: 'bold' }}>
            KPMG Client Compliance Tool
          </h1>
          <p style={{ marginBottom: '40px', color: '#666', fontSize: '16px', lineHeight: '1.5' }}>
            Please sign in with your KPMG Microsoft account
          </p>
          <button
            onClick={handleLogin}
            disabled={loading}
            style={{
              padding: '12px 32px',
              fontSize: '16px',
              background: 'linear-gradient(180deg, #0077ea, #0057c2)',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
              fontWeight: 'bold',
              transition: 'all 0.2s',
              width: '100%',
              boxShadow: '0 4px 12px rgba(0, 119, 234, 0.3)'
            }}
            onMouseOver={(e) => !loading && (e.target.style.transform = 'translateY(-2px)', e.target.style.boxShadow = '0 6px 16px rgba(0, 119, 234, 0.4)')}
            onMouseOut={(e) => (e.target.style.transform = 'translateY(0)', e.target.style.boxShadow = '0 4px 12px rgba(0, 119, 234, 0.3)')}
          >
            {loading ? 'Signing in...' : 'Sign In with Microsoft'}
          </button>
          
          <button
            onClick={() => setBypassAuth(true)}
            style={{
              marginTop: '16px',
              padding: '10px 24px',
              fontSize: '14px',
              background: 'transparent',
              color: '#666',
              border: '1px solid #ddd',
              borderRadius: '6px',
              cursor: 'pointer',
              fontWeight: '500',
              transition: 'all 0.2s',
              width: '100%'
            }}
            onMouseOver={(e) => (e.target.style.backgroundColor = '#f8f8f8', e.target.style.borderColor = '#bbb')}
            onMouseOut={(e) => (e.target.style.backgroundColor = 'transparent', e.target.style.borderColor = '#ddd')}
          >
            Bypass login for application trial
          </button>
        </div>
      </div>
    );
  }

  return (
    <BypassAuthContext.Provider value={{ bypassAuth, setBypassAuth }}>
      {children}
    </BypassAuthContext.Provider>
  );
};

export default AuthenticationComponent;
