// Cloudflare Worker — 카카오맵 CCTV의 영상 주소를 대신 받아 CORS를 열어 주는 중계
// 사용: 이 코드를 새 Worker에 붙여넣고 배포 → 주소 뒤에 ?key=4485 를 붙여 앱의 links.roadApi에 넣는다.
export default {
  async fetch(req) {
    const cors = { 'access-control-allow-origin': '*', 'cache-control': 'no-store' };
    if (req.method === 'OPTIONS') return new Response(null, { headers: { ...cors, 'access-control-allow-methods': 'GET' } });
    const key = (new URL(req.url).searchParams.get('key') || '4485').replace(/\D/g, '').slice(0, 8);
    const r = await fetch(`https://map.kakao.com/api/cctvs/url/${key}`, {
      headers: { 'user-agent': 'Mozilla/5.0', 'referer': `https://map.kakao.com/?cctv=${key}`, 'accept': 'application/json' },
    });
    return new Response(await r.text(), { status: r.status, headers: { ...cors, 'content-type': 'application/json' } });
  },
};
