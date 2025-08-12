let ws;
let mediaRecorder;
let chunks = [];
let pushToTalk = true;
let vadBargeIn = false;

const providers = {
  stt: document.getElementById('provider-stt'),
  llm: document.getElementById('provider-llm'),
  tts: document.getElementById('provider-tts'),
  avatar: document.getElementById('provider-avatar'),
};

const audioEl = document.getElementById('audio');
const avatarEl = document.getElementById('avatar');

function setAvatar(open) {
  avatarEl.textContent = open ? '😃' : '🙂';
}

async function fetchFlags() {
  try {
    const res = await fetch('http://localhost:8080/flags');
    const data = await res.json();
    const list = (data.flags || []).reduce((acc, f) => { acc[f.name] = f; return acc; }, {});
    pushToTalk = !!(list['PUSH_TO_TALK'] && list['PUSH_TO_TALK'].enabled);
    vadBargeIn = !!(list['VAD_BARGE_IN'] && list['VAD_BARGE_IN'].enabled);
    document.getElementById('btn-vad').style.display = vadBargeIn ? 'inline-block' : 'none';
  } catch {}
}

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  ws = new WebSocket('ws://localhost:8080/ws/audio?session_id=local&user_id=local-user');
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    console.log('WS open');
  };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'partial_transcript') {
        const div = document.getElementById('partials');
        div.textContent += msg.text + '\n';
      } else if (msg.type === 'llm_token') {
        const t = document.getElementById('first-token');
        t.textContent = msg.token;
      } else if (msg.type === 'tts_chunk') {
        // feed small silence to keep audio alive; backend already streams timing
        // this demo uses avatar open/close cadence only
        setAvatar((Date.now() % 400) < 200);
      } else if (msg.type === 'avatar_chunk') {
        // could map frame payload to UI; we simply toggle icon
        setAvatar((Date.now() % 400) < 200);
      } else if (msg.type === 'done') {
        console.log('turn done');
      }
    } catch (e) {
      // not JSON
    }
  };
}

async function startMic() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) {
      e.data.arrayBuffer().then((buf) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
      });
    }
  };
  mediaRecorder.start(100);
}

function stopMic() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
}

document.getElementById('btn-connect').onclick = connect;
document.getElementById('btn-disconnect').onclick = () => ws && ws.close();

let pttDown = false;
window.addEventListener('keydown', (e) => {
  if (pushToTalk && e.code === 'Space' && !pttDown) {
    pttDown = true;
    startMic();
  }
});
window.addEventListener('keyup', (e) => {
  if (pushToTalk && e.code === 'Space' && pttDown) {
    pttDown = false;
    stopMic();
  }
});

// initialize flags
fetchFlags();


// telemetry wiring
window.updateTelemetry = (p) => {
  try {
    document.getElementById('tokens-in').textContent = p.tokens_in || 0;
    document.getElementById('tokens-out').textContent = p.tokens_out || 0;
    const price = p.price_usd || 0;
    const val = typeof price === 'number' ? price : parseFloat(price);
    document.getElementById('price-usd').textContent = (isNaN(val) ? 0 : val).toFixed(4);
  } catch {}
};



fetch('/achievements.json').then(r=>r.json()).then(d=>{window.achievements=d.badges||[];}).catch(()=>{});
