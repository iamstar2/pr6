// Zero-Touch Media Control 웹서버 (Windows 네이티브 전용, Docker/WSL 사용 안 함)
// - public 폴더를 정적으로 제공
// - /api/youtube 는 계정/API Key 없이 YouTube 검색 결과 페이지(HTML)를 그대로 가져와
//   내장된 ytInitialData JSON에서 영상 목록만 뽑아 돌려준다 (비공식 방식이라
//   YouTube가 검색 결과 페이지 구조를 바꾸면 파싱이 깨질 수 있음)
// - 얼굴 인식 신호는 ESP32 -> Mosquitto(MQTT) -> 브라우저(MQTT.js) 로 직접 전달되며
//   이 서버는 관여하지 않는다 (정적 파일 제공 + YouTube 검색 역할만 수행)
const express = require('express');
const path = require('path');

const app = express();
const PORT = 3000;

app.use(express.static(path.join(__dirname, 'public')));

// YouTube 검색: GET /api/youtube?q=검색어
app.get('/api/youtube', async (req, res) => {
  const q = req.query.q;
  if (!q) {
    return res.status(400).json({ error: 'query parameter q is required' });
  }

  try {
    const searchUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}&hl=ko&gl=KR`;
    const ytRes = await fetch(searchUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Language': 'ko-KR'
      }
    });
    const html = await ytRes.text();

    // 검색 결과 페이지 안에 박혀 있는 초기 데이터(JSON) 추출
    const match = html.match(/var ytInitialData = (\{.+?\});<\/script>/s);
    if (!match) {
      return res.status(502).json({ error: 'YouTube 검색 결과를 해석하지 못했습니다' });
    }
    const data = JSON.parse(match[1]);

    const sections =
      data.contents?.twoColumnSearchResultsRenderer?.primaryContents
        ?.sectionListRenderer?.contents || [];

    const items = [];
    for (const section of sections) {
      const contents = section.itemSectionRenderer?.contents || [];
      for (const c of contents) {
        const v = c.videoRenderer;
        if (!v?.videoId) continue; // 채널/재생목록 등 영상이 아닌 결과는 건너뜀
        items.push({
          id: { videoId: v.videoId },
          snippet: {
            title: v.title?.runs?.[0]?.text || '(제목 없음)',
            thumbnails: {
              medium: { url: v.thumbnail?.thumbnails?.slice(-1)[0]?.url || '' }
            }
          }
        });
        if (items.length >= 8) break;
      }
      if (items.length >= 8) break;
    }

    res.json({ items });
  } catch (err) {
    res.status(500).json({ error: 'YouTube 검색 요청 실패' });
  }
});

app.listen(PORT, () => {
  console.log(`Zero-Touch Media Control server running at http://localhost:${PORT}`);
});
