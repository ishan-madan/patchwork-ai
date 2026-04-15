// quiz.js

// Fetch questions from CSV and run quiz
const questionArea = document.getElementById('question-area');
const optionsArea = document.getElementById('options-area');
const nextBtn = document.getElementById('next-btn');
const quizContainer = document.getElementById('quiz-container');

let questions = [];
let answers = [];
let current = 0;


// Robust CSV parser for quoted fields with commas
function csvToArray(str) {
  const rows = str.trim().split('\n');
  const headers = rows[0].split(',').map(h => h.trim());
  return rows.slice(1).map(row => {
    const values = [];
    let inQuotes = false, value = '';
    for (let i = 0; i < row.length; i++) {
      const char = row[i];
      if (char === '"') {
        inQuotes = !inQuotes;
      } else if (char === ',' && !inQuotes) {
        values.push(value);
        value = '';
      } else {
        value += char;
      }
    }
    values.push(value);
    const obj = {};
    headers.forEach((h, i) => obj[h] = (values[i] || '').replace(/^"|"$/g, ''));
    return obj;
  });
}

function showQuestion(idx) {
  const q = questions[idx];
  questionArea.textContent = q.question;
  optionsArea.innerHTML = '';
  Object.keys(q).filter(k => k.startsWith('option') && q[k]).forEach(optKey => {
    const btn = document.createElement('button');
    btn.className = 'primary';
    btn.textContent = q[optKey];
    btn.onclick = () => {
      answers[idx] = q[optKey];
      // Remove 'selected' from all buttons
      Array.from(optionsArea.children).forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      nextBtn.style.display = 'block';
    };
    optionsArea.appendChild(btn);
  });
  nextBtn.style.display = 'none';
}

function finishQuiz() {
  // Format: "Q1:Answer1, Q2:Answer2, ..."
  const formatted = questions.map((q, i) => `${q.question}:${answers[i]}`).join(', ');
  // Store in sessionStorage
  sessionStorage.setItem('quizAnswers', formatted);
  // Show popup
  alert('Please hit enter once you see the welcome message, regardless of what the welcome message is.');
  // Redirect to chat
  window.location.href = 'chat.html?fromQuiz=1';
}

nextBtn.onclick = function() {
  if (current < questions.length - 1) {
    current++;
    showQuestion(current);
  } else {
    finishQuiz();
  }
};

fetch('../data/questions.csv')
  .then(r => r.text())
  .then(text => {
    questions = csvToArray(text);
    answers = Array(questions.length).fill('');
    showQuestion(0);
  });
