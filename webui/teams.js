/* Team identity for every screen: a colour and a short code for each nation and franchise, badges, initials
   avatars and display names without a shared year ("Punjab Kings" instead of "Punjab Kings 2026" when every team
   in a run is from 2026). Colours are the sides' best-known colours, not official values. Presentation only. */
'use strict';

// key -> [short, background, text, accent]
const TEAM_ID = {
  // nations
  'India': ['IND', '#1f6fd1', '#fff', '#ff9933'], 'Australia': ['AUS', '#ffcd00', '#003b1f', '#00843d'],
  'England': ['ENG', '#1d3c8f', '#fff', '#e4002b'], 'Pakistan': ['PAK', '#01693d', '#fff', '#a7d65a'],
  'South Africa': ['RSA', '#007a4d', '#fff', '#ffb612'], 'New Zealand': ['NZ', '#111', '#fff', '#9aa3ad'],
  'Sri Lanka': ['SL', '#0b3f8f', '#fff', '#f7b500'], 'West Indies': ['WI', '#7b1e3a', '#fff', '#f2c230'],
  'Bangladesh': ['BAN', '#006a4e', '#fff', '#f42a41'], 'Afghanistan': ['AFG', '#1a5fb4', '#fff', '#d32f2f'],
  'Zimbabwe': ['ZIM', '#d40000', '#fff', '#ffd200'], 'Ireland': ['IRE', '#169b62', '#fff', '#ff883e'],
  'Netherlands': ['NED', '#f36c21', '#fff', '#21468b'], 'Scotland': ['SCO', '#1b3f8b', '#fff', '#a7b6d8'],
  'Kenya': ['KEN', '#006600', '#fff', '#bb0000'], 'Namibia': ['NAM', '#003580', '#fff', '#d21034'],
  'Nepal': ['NEP', '#dc143c', '#fff', '#003893'], 'United Arab Emirates': ['UAE', '#00732f', '#fff', '#ff0000'],
  'Oman': ['OMA', '#db161b', '#fff', '#008000'], 'United States of America': ['USA', '#002868', '#fff', '#bf0a30'],
  'Canada': ['CAN', '#d52b1e', '#fff', '#fff'], 'Papua New Guinea': ['PNG', '#ce1126', '#fff', '#fcd116'],
  'Hong Kong': ['HK', '#de2910', '#fff', '#fff'], 'Uganda': ['UGA', '#fcdc04', '#111', '#d90000'],
  // franchises (the auction room's table, kept in step)
  'Chennai Super Kings': ['CSK', '#F9CD05', '#1a1a1a', '#0081E9'], 'Mumbai Indians': ['MI', '#004BA0', '#fff', '#D1AB3E'],
  'Royal Challengers Bengaluru': ['RCB', '#2B2A29', '#fff', '#EC1C24'], 'Royal Challengers Bangalore': ['RCB', '#2B2A29', '#fff', '#EC1C24'],
  'Kolkata Knight Riders': ['KKR', '#3A225D', '#fff', '#B3A123'], 'Sunrisers Hyderabad': ['SRH', '#F26522', '#000', '#000'],
  'Rajasthan Royals': ['RR', '#EA1A85', '#fff', '#254AA5'], 'Delhi Capitals': ['DC', '#17479E', '#fff', '#EF1B23'],
  'Delhi Daredevils': ['DD', '#1A2A6C', '#fff', '#EF1B23'], 'Punjab Kings': ['PBKS', '#D71920', '#fff', '#DCDDDF'],
  'Kings XI Punjab': ['KXIP', '#D71920', '#fff', '#DCDDDF'], 'Gujarat Titans': ['GT', '#1B2133', '#fff', '#B8975A'],
  'Lucknow Super Giants': ['LSG', '#0057E2', '#fff', '#F28B00'], 'Deccan Chargers': ['DEC', '#1D3F6E', '#fff', '#C0C0C0'],
  'Gujarat Lions': ['GL', '#E04F16', '#fff', '#1D1D1B'], 'Kochi Tuskers Kerala': ['KTK', '#5B2C83', '#fff', '#F28C28'],
  'Pune Warriors': ['PWI', '#2F9BD6', '#000', '#1B1B1B'], 'Rising Pune Supergiant': ['RPS', '#252C64', '#fff', '#D1176C'],
  'Rising Pune Supergiants': ['RPS', '#252C64', '#fff', '#D1176C'],
  'Adelaide Strikers': ['STR', '#00A3E0', '#000', '#002B5C'], 'Brisbane Heat': ['HEA', '#00B2A9', '#000', '#E4002B'],
  'Hobart Hurricanes': ['HUR', '#6A2C91', '#fff', '#A6CE39'], 'Melbourne Renegades': ['REN', '#D71920', '#fff', '#1D1D1B'],
  'Melbourne Stars': ['STA', '#00A651', '#000', '#004225'], 'Perth Scorchers': ['SCO', '#F47920', '#000', '#1D1D1B'],
  'Sydney Sixers': ['SIX', '#E6007E', '#fff', '#1D1D1B'], 'Sydney Thunder': ['THU', '#A6CE39', '#000', '#1D1D1B'],
  'Islamabad United': ['IU', '#E31B23', '#fff', '#1D1D1B'], 'Karachi Kings': ['KK', '#0072BC', '#fff', '#E31B23'],
  'Lahore Qalandars': ['LQ', '#00A651', '#000', '#E31B23'], 'Multan Sultans': ['MS', '#00A79D', '#000', '#F8C300'],
  'Peshawar Zalmi': ['PZ', '#FDB913', '#000', '#1D1D1B'], 'Quetta Gladiators': ['QG', '#6A2C91', '#fff', '#FDB913'],
  'MI Cape Town': ['MICT', '#004BA0', '#fff', '#D1AB3E'], 'MI Emirates': ['MIE', '#004BA0', '#fff', '#D1AB3E'],
  'MI New York': ['MINY', '#004BA0', '#fff', '#D1AB3E'], 'Joburg Super Kings': ['JSK', '#F9CD05', '#1a1a1a', '#0081E9'],
  'Texas Super Kings': ['TSK', '#F9CD05', '#1a1a1a', '#0081E9'], 'Sunrisers Eastern Cape': ['SEC', '#F26522', '#000', '#000'],
  'Paarl Royals': ['PR', '#EA1A85', '#fff', '#254AA5'], 'Barbados Royals': ['BR', '#EA1A85', '#fff', '#254AA5'],
  'Pretoria Capitals': ['PC', '#17479E', '#fff', '#EF1B23'], 'Dubai Capitals': ['DCP', '#17479E', '#fff', '#EF1B23'],
  "Durban's Super Giants": ['DSG', '#0057E2', '#fff', '#F28B00'], 'Abu Dhabi Knight Riders': ['ADKR', '#3A225D', '#fff', '#B3A123'],
  'Los Angeles Knight Riders': ['LAKR', '#3A225D', '#fff', '#B3A123'], 'Trinbago Knight Riders': ['TKR', '#C8102E', '#fff', '#1D1D1B'],
};
// leagues (setup cards)
const LEAGUE_ID = {ipl: ['IPL', '#1d2c6b', '#fff', '#f28b00', 'India'], bbl: ['BBL', '#f26522', '#000', '#000', 'Australia'],
  psl: ['PSL', '#00843d', '#fff', '#c9a227', 'Pakistan'], cpl: ['CPL', '#e4002b', '#fff', '#ffd100', 'West Indies'],
  sat: ['SA20', '#00a3e0', '#000', '#1d1d1b', 'South Africa'], ilt: ['ILT20', '#5b2c83', '#fff', '#f6c453', 'UAE'],
  bpl: ['BPL', '#006a4e', '#fff', '#f42a41', 'Bangladesh'], lpl: ['LPL', '#1b3a8a', '#fff', '#ffbe29', 'Sri Lanka'],
  mlc: ['MLC', '#002868', '#fff', '#bf0a30', 'USA'], ntb: ['BLAST', '#0b1e5b', '#fff', '#e30613', 'England'],
  ssm: ['SMASH', '#111', '#fff', '#2ee88a', 'New Zealand']};
const TEAM_PAL = ['#4c8dff', '#e3b341', '#2fbf71', '#f85149', '#a371f7', '#f778ba', '#39c5cf', '#ff9f43', '#7ee787', '#d2a8ff', '#ffa198', '#79c0ff'];

// "Punjab Kings 2026" / "India T20 2024" / "India 2007-11" -> "Punjab Kings" / "India"
function teamKey(name) {
  let s = String(name || '').trim(), prev;
  do { prev = s; s = s.replace(/\s+(\d{4}(?:\s*[-–]\s*\d{2,4})?|T20I?|ODI|XI)$/i, ''); } while (s !== prev && s);
  return s || String(name || '');
}
const _lum = h => { const n = parseInt(h.slice(1).padEnd(6, '0').slice(0, 6), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map(v => v / 255);
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
function _short(k) {
  const w = k.split(/[\s&]+/).filter(x => x && !/^(and|of|the)$/i.test(x));
  return w.length === 1 ? w[0].slice(0, 3).toUpperCase() : w.map(x => /^\d+$/.test(x) ? x : x[0].toUpperCase()).join('').slice(0, 4);
}
const _TC = new Map();
function tcol(name) {
  if (_TC.has(name)) return _TC.get(name);
  const k = teamKey(name);
  let [short, c, f, a] = TEAM_ID[k] || [];
  if (!short) {
    let h = 0; for (const ch of k) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    short = _short(k); c = TEAM_PAL[h % TEAM_PAL.length]; f = _lum(c) > 0.45 ? '#111' : '#fff'; a = 'rgba(0,0,0,.35)';
  }
  // `hi`: a version of the colour that reads on the dark page (very dark kits use their accent)
  const hi = _lum(c) < 0.07 ? (a && a[0] === '#' && _lum(a) > 0.1 ? a : '#9aa3ad') : c;
  const out = {key: k, short, c, f, a: a || 'rgba(0,0,0,.35)', hi};
  _TC.set(name, out);
  return out;
}
const tStyle = name => { const t = tcol(name); return `--c:${t.c};--f:${t.f};--a:${t.a};--hi:${t.hi}`; };
const badge = (name, cls = '') => `<span class="badge ${cls}" style="${tStyle(name)}" title="${esc(name)}">${esc(tcol(name).short)}</span>`;
const initials = n => String(n || '').replace(/[†*]/g, '').split(/\s+/).filter(Boolean).map(w => w[0]).join('').slice(0, 2).toUpperCase();
const avatar = (player, team, cls = '') => `<span class="ini ${cls}" style="${tStyle(team)}">${esc(initials(player))}</span>`;

/* display names: drop the words every team in the run shares at the end ("2026", "T20 2024") */
let DN_CUT = '';
function setDisplayTeams(teams) {
  DN_CUT = '';
  const list = [...new Set((teams || []).filter(Boolean))];
  if (list.length < 2) { if (list.length === 1) { const k = teamKey(list[0]); DN_CUT = k !== list[0] ? list[0].slice(k.length) : ''; } return; }
  const words = list.map(t => t.split(' '));
  let n = 0;
  while (words.every(w => w.length > n + 1 && w[w.length - 1 - n] === words[0][words[0].length - 1 - n])) n++;
  if (!n) return;
  const cut = ' ' + words[0].slice(-n).join(' ');
  const short = list.map(t => t.slice(0, -cut.length));
  if (new Set(short).size === list.length) DN_CUT = cut;
}
const dn = t => t && DN_CUT && String(t).endsWith(DN_CUT) ? String(t).slice(0, -DN_CUT.length) : (t || '');
const dnText = (s, teams) => { let o = String(s || ''); if (DN_CUT) (teams || []).forEach(t => { if (t) o = o.split(t).join(dn(t)); }); return o; };
