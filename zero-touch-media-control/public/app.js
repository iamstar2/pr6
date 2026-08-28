// Zero-Touch Media Control - 브라우저 로직
// - MQTT.js로 Windows용 Mosquitto의 WebSocket 리스너(9001)에 접속해
//   zero_touch/face 토픽을 구독한다 (ESP32 -> Mosquitto -> 브라우저 직결, 서버는 중계하지 않음)
// - face=1이면 재생, face=0이면 일시정지
// - YouTube 검색은 서버의 /api/youtube 프록시를 통해 수행 (API Key는 서버에만 존재)

const mqttStatusEl = document.getElementById('mqtt-status');
const faceStatusEl = document.getElementById('face-status');
const searchInput = document.getElementById('search-input');
const searchBtn = document.getElementById('search-btn');
const resultsEl = document.getElementById('results');

let player = null;
let playerReady = false;
let currentFace = 0;        // 최신 얼굴 인식 상태 (0: 미인식, 1: 인식)
let pendingVideoId = null;  // player가 준비되기 전에 선택된 영상을 대기시켜둠

// ---------- MQTT ----------
// ESP32는 zero_touch/face 토픽으로 {"face":1} / {"face":0} 을 publish 한다.
const mqttUrl = `ws://${location.hostname}:9001`;
const client = mqtt.connect(mqttUrl);

client.on('connect', () => {
  setMqttStatus('CONNECTED');
  client.subscribe('zero_touch/face');
});

// 아직 연결되지 않았거나(초기/재접속 시도 중) 끊긴 경우 -> WAITING/DISCONNECTED로 구분 표시
client.on('reconnect', () => setMqttStatus('WAITING'));
client.on('close', () => setMqttStatus('DISCONNECTED'));
client.on('offline', () => setMqttStatus('DISCONNECTED'));
client.on('error', () => setMqttStatus('DISCONNECTED'));

client.on('message', (topic, payload) => {
  if (topic !== 'zero_touch/face') return;
  try {
    const data = JSON.parse(payload.toString());
    currentFace = data.face === 1 ? 1 : 0;
    setFaceStatus(currentFace);
    applyFaceToPlayer();
  } catch (e) {
    console.error('invalid MQTT payload:', payload.toString());
  }
});

function setMqttStatus(state) {
  mqttStatusEl.textContent = `MQTT : ${state}`;
  mqttStatusEl.className = `badge ${state.toLowerCase()}`;
}

function setFaceStatus(face) {
  const label = face === 1 ? 'DETECTED' : 'NOT DETECTED';
  faceStatusEl.textContent = `FACE : ${label}`;
  faceStatusEl.className = `badge ${face === 1 ? 'detected' : 'not-detected'}`;
}

function applyFaceToPlayer() {
  if (!playerReady || !player) return;
  if (currentFace === 1) {
    player.playVideo();
  } else {
    player.pauseVideo();
  }
}

// ---------- YouTube IFrame Player ----------
// youtube iframe_api 스크립트가 로드되면 자동으로 이 전역 함수를 호출한다.
function onYouTubeIframeAPIReady() {
  player = new YT.Player('player', {
    height: '360',
    width: '640',
    videoId: '',
    events: {
      onReady: onPlayerReady
    }
  });
}

function onPlayerReady() {
  playerReady = true;
  player.mute(); // 브라우저 자동재생 제한 대응: player 준비 시점에 음소거

  if (pendingVideoId) {
    loadSelectedVideo(pendingVideoId);
    pendingVideoId = null;
  }
}

// 검색 결과 클릭 시 영상 로드
// 선택 당시 face=0 이면 일시정지 상태로 준비, face=1 이면 바로 재생
function loadSelectedVideo(videoId) {
  if (!playerReady) {
    pendingVideoId = videoId;
    return;
  }
  if (currentFace === 1) {
    player.loadVideoById(videoId);
  } else {
    player.cueVideoById(videoId);
  }
}

// ---------- YouTube 검색 ----------
async function searchYoutube() {
  const q = searchInput.value.trim();
  if (!q) return;

  resultsEl.textContent = '검색 중...';
  try {
    const res = await fetch(`/api/youtube?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    if (!res.ok) {
      resultsEl.textContent = `검색 오류: ${data.error || '알 수 없는 오류'}`;
      return;
    }
    renderResults(data.items || []);
  } catch (e) {
    resultsEl.textContent = '검색 요청 실패';
  }
}

function renderResults(items) {
  resultsEl.innerHTML = '';
  items.forEach(item => {
    const videoId = item.id.videoId;
    const title = item.snippet.title;
    const thumbUrl = item.snippet.thumbnails.medium.url;

    const card = document.createElement('div');
    card.className = 'result-card';

    const img = document.createElement('img');
    img.src = thumbUrl;
    img.alt = title;

    const caption = document.createElement('p');
    caption.textContent = title;

    card.appendChild(img);
    card.appendChild(caption);
    card.addEventListener('click', () => loadSelectedVideo(videoId));

    resultsEl.appendChild(card);
  });
}

searchBtn.addEventListener('click', searchYoutube);
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') searchYoutube();
});
