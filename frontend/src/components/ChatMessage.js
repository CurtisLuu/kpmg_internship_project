import React from 'react';
import ReactMarkdown from 'react-markdown';
import './ChatMessage.css';

function ChatMessage({ message }) {
  const isUser = message.role === 'user';
  
  return (
    <div className={`chat-message ${isUser ? 'user-message' : 'assistant-message'} ${message.isError ? 'error-message' : ''}`}>
      <div className="message-content">
        <div className="message-role">
          {isUser ? 'You' : 'AI Assistant'}
        </div>
        <div className="message-text">
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>
        <div className="message-timestamp">
          {new Date(message.timestamp).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}

export default ChatMessage;
