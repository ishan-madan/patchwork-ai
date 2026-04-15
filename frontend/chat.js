

const socket = io('http://localhost:8080');
const chatArea = document.getElementById('chat-area');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const sendButton = chatForm.querySelector('button[type="submit"]');
const restartBtn = document.getElementById('restart-chat-btn');
const endChatBtn = document.getElementById('end-chat-btn');
const feedbackOverlay = document.getElementById('feedback-overlay');
const feedbackForm = document.getElementById('feedback-form');
// Show feedback overlay
function showFeedbackForm() {
  if (feedbackOverlay) {
    feedbackOverlay.style.display = 'flex';
    feedbackOverlay.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }
}

// Hide feedback overlay
function hideFeedbackForm() {
  if (feedbackOverlay) feedbackOverlay.style.display = 'none';
}
// Listen for end chat button
if (endChatBtn) {
  endChatBtn.addEventListener('click', function() {
    showFeedbackForm();
    disableChatInput();
  });
}
// Listen for feedback form submit
if (feedbackForm) {
  feedbackForm.addEventListener('submit', function(e) {
    e.preventDefault();
    const rating = feedbackForm.elements['rating'].value;
    const recommend = feedbackForm.elements['recommend'].value;
    const feedback = feedbackForm.elements['feedback'].value;
    const payload = { rating, recommend, feedback };
    // Send feedback to backend
    fetch('http://localhost:8080/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then((res) => {
      if (res.ok) {
        feedbackOverlay.innerHTML = '<div style="padding:2rem;text-align:center;">Thank you for your feedback!</div>';
        setTimeout(() => {
          window.location.href = window.location.origin + '/index.html';
        }, 5000);
      } else {
        console.log(res)
        feedbackOverlay.innerHTML = '<div style="padding:2rem;text-align:center;">Error submitting feedback.</div>';
      }
    }).catch(() => {
      console.log(res)
      feedbackOverlay.innerHTML = '<div style="padding:2rem;text-align:center;">Error submitting feedback.</div>';
    });
  });
}

let thinkingBubble = null;

function clearChat() {
  chatArea.innerHTML = '';
  thinkingBubble = null;
}

function restartChat() {
  socket.emit('restart_chat');
  clearChat();
}

// Restart chat on page load

window.addEventListener('DOMContentLoaded', () => {
  restartChat();
  // If coming from quiz, prefill chat input and show popup
  const quizAnswers = sessionStorage.getItem('quizAnswers');
  const urlParams = new URLSearchParams(window.location.search);
  if (quizAnswers && urlParams.get('fromQuiz') === '1') {
    chatInput.value = quizAnswers;
    setTimeout(() => {
      alert('Please hit enter once you see the welcome message, regardless of what the welcome message is.');
    }, 500);
    // Optionally clear after use
    sessionStorage.removeItem('quizAnswers');
  }
});

if (restartBtn) {
  restartBtn.addEventListener('click', restartChat);
}


function appendBubble(content, type) {
  const div = document.createElement('div');
  if (type === 'course_card' && typeof content === 'object') {
    div.className = 'card course_card';
    div.innerHTML = `
      <div class="course-title">${content.course || ''} — ${content.title || ''}</div>
      <div class="course-meta">Units: ${content.units || ''} | Career: ${content.career || ''}</div>
      <div class="course-reason">${content.reason || ''}</div>
    `;
  } else if (type === 'prereq_prompt') {
    div.className = 'bubble advisor';
    div.textContent = content;
    // Add Yes/No buttons
    const btnWrap = document.createElement('div');
    btnWrap.style.marginTop = '1rem';
    btnWrap.style.display = 'flex';
    btnWrap.style.gap = '1rem';
    const yesBtn = document.createElement('button');
    yesBtn.textContent = 'Yes';
    yesBtn.className = 'prereq-btn yes';
    const noBtn = document.createElement('button');
    noBtn.textContent = 'No';
    noBtn.className = 'prereq-btn no';
    yesBtn.onclick = function() {
      socket.emit('user_message', 'yes');
      appendBubble('Yes', 'user');
      enableChatInput();
      div.remove();
    };
    noBtn.onclick = function() {
      socket.emit('user_message', 'no');
      appendBubble('No', 'user');
      enableChatInput();
      div.remove();
    };
    btnWrap.appendChild(yesBtn);
    btnWrap.appendChild(noBtn);
    div.appendChild(btnWrap);
  } else {
    div.className = 'bubble ' + (type || 'system');
    div.textContent = content;
  }
  chatArea.appendChild(div);
  chatArea.scrollTop = chatArea.scrollHeight;
  return div;
}

function disableChatInput() {
//   chatInput.disabled = true;
  if (sendButton) sendButton.disabled = true;
}
function enableChatInput() {
//   chatInput.disabled = false;
  if (sendButton) sendButton.disabled = false;
}

function showThinking() {
  if (!thinkingBubble) {
    thinkingBubble = appendBubble('Thinking...', 'system');
    thinkingBubble.classList.add('thinking-bubble');
  }
}

function hideThinking() {
  if (thinkingBubble && thinkingBubble.parentNode) {
    thinkingBubble.parentNode.removeChild(thinkingBubble);
    thinkingBubble = null;
  }
}


socket.on('connect', () => {
  appendBubble('Connected to advisor.', 'system');
});


socket.on('message', (data) => {
  if (data && data.type === 'system' && data.content === 'Chat restarted.') {
    clearChat();
    return;
  }
  if (!data) return;
  if (data.type === 'waiting') {
    if (data.content === true) {
      showThinking();
      disableChatInput();
    } else {
      hideThinking();
      enableChatInput();
    }
    return;
  }
  // Special handling for prereq prompt
  if (typeof data.content === 'string' && /have you met these prerequisites\?/i.test(data.content)) {
    appendBubble(data.content, 'prereq_prompt');
    disableChatInput();
    return;
  }
  // Special handling for course acceptance prompt
  if (typeof data.content === 'string' && /do you want to take this course\?/i.test(data.content)) {
    appendBubble(data.content, 'prereq_prompt');
    disableChatInput();
    // Listen for user acceptance (Yes button)
    // The prereq_prompt Yes/No logic is above, so hook into it:
    // If user clicks Yes, show feedback form
    // We'll monkey-patch the Yes button after it's created
    setTimeout(() => {
      const yesBtn = document.querySelector('.prereq-btn.yes');
      if (yesBtn) {
        const orig = yesBtn.onclick;
        yesBtn.onclick = function() {
          if (orig) orig();
          showFeedbackForm();
        };
      }
      const noBtn = document.querySelector('.prereq-btn.no');
      if (noBtn) {
        const origNo = noBtn.onclick;
        noBtn.onclick = function() {
          if (origNo) origNo();
          // Optionally, you could show feedback here too
        };
      }
    }, 100);
    return;
  }
  if (data.type === 'input_prompt') {
    // Show as advisor message, but focus input
    if (data.content && data.content.trim()) {
      appendBubble(data.content, 'advisor');
    }
    chatInput.focus();
    return;
  }
  if (data.type === 'advisor') {
    appendBubble(data.content, 'advisor');
  } else if (data.type === 'system') {
    appendBubble(data.content, 'system');
  } else if (data.type === 'recommendation') {
    appendBubble(data.content, 'recommendation');
  } else if (data.type === 'course_card') {
    appendBubble(data.content, 'course_card');
  } else {
    appendBubble(data.content, 'system');
  }
});



chatForm.addEventListener('submit', function(e) {
  e.preventDefault();
  const msg = chatInput.value.trim();
  if (!msg) return;
  appendBubble(msg, 'user');
  socket.emit('user_message', msg);
  chatInput.value = '';
  chatInput.focus();
});
