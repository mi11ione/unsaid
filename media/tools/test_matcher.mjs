// Parity of site/js/matcher.js with engine/unsaid/matcher.py (norm, distinctive, head, tok_eq), plus dare-box cases.
//   node media/tools/test_matcher.mjs        (from /Users/mi11ion/Desktop/qloo/unsaid)
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
const require = createRequire(import.meta.url);
const M = require('../../site/js/matcher.js');

const wall = JSON.parse(readFileSync('site/data/walls/stl.json', 'utf8'));
const names = [...new Set(wall.answers.flatMap(a => a.names))];
const extra = ["Charlie Gitto's on The Hill", 'Lobby Bar at Hotel Chelsea', 'Café Ñandú & Co.', "Pappy’s Smoke House", 'Bar-B-Que Joint',
  'Saint Louis Bread Co.', 'The Mount Pleasant Tap Room', 'Gioia\'s Deli (hot salami sandwich)', 'BB\'s Jazz, Blues & Soups', "Marsha's", 'Marshas Ltd', 'Acme Pizza Co.', 'Blue Co Coffee', "Jody B'", "Jody B's", 'Pappys', "Rock 'n' Roll Bar", "The Brothers'"];
const all = names.concat(extra);
const py = `
import json, sys, difflib
sys.path.insert(0, 'engine')
from unsaid.matcher import norm, distinctive, split_parts, tok_eq
names = json.load(sys.stdin)
pairs = [["smokehouse","smokehous"],["gioia","gioias"],["louie","louis"],["mekong","mekang"]]
print(json.dumps({"norm":[norm(n) for n in names], "dist":[distinctive(n) for n in names],
  "head":[split_parts(n)[2] or split_parts(n)[0] for n in names], "tok":[tok_eq(a,b) for a,b in pairs], "pairs":pairs}))`;
const P = JSON.parse(execFileSync('python3', ['-I', '-c', py], { input: JSON.stringify(all) }));
let bad = 0;
all.forEach((n, i) => {
  if (M.norm(n) !== P.norm[i]) { bad++; console.log('norm', JSON.stringify(n), M.norm(n), '!=', P.norm[i]); }
  if (JSON.stringify(M.distinctive(n)) !== JSON.stringify(P.dist[i])) { bad++; console.log('dist', n, M.distinctive(n), P.dist[i]); }
  if (M.head(n) !== P.head[i]) { bad++; console.log('head', JSON.stringify(n), JSON.stringify(M.head(n)), '!=', JSON.stringify(P.head[i])); }
});
P.pairs.forEach(([a, b], i) => { if (M.tokEq(a, b) !== P.tok[i]) { bad++; console.log('tok_eq', a, b); } });

// dare-box cases: [pasted text, card names, expected hits]
const cards = ["Jody B'", "Marshas Ltd", "Gioia's Deli", 'Smoki O\'s', 'The Royale', 'Mekong Restaurant', 'Pho Grand', "Pappy's Smokehouse", null];
const cases = [
  ['Try Gioias deli on the Hill, then Pho Grand.', ["Gioia's Deli", 'Pho Grand']],
  ['1. **Smoki O’s** (North Broadway): rib tips', ['Smoki O\'s']],
  ['Pappy\'s Smoke House is the classic.', ["Pappy's Smokehouse"]],
  ['Grab a pho at a grand old place', ['Pho Grand']],          // unsure -> strikes (window rule)
  ['Nothing here but a royal flush and some noodles.', ['The Royale']], // tok_eq: royal~royale 0.91, unsure -> strike
  ['Nothing here but noodles and a flush.', []],
  ['Head to the Royale on Kingshighway', ['The Royale']],
  ['Mekong for banh mi', ['Mekong Restaurant']],
  ["Marsha's, for the fried fish", ['Marshas Ltd']],                 // apostrophe + corporate suffix (29 Oct)
  ['Marshas on Natural Bridge', ['Marshas Ltd']],
  ["Rib tips at Jody B's on Natural Bridge", ["Jody B'"]],                 // Qloo's cut possessive (29 Oct)
];
for (const [t, want] of cases) {
  const got = M.find(t, cards).map(h => h.name);
  if (JSON.stringify(got) !== JSON.stringify(want)) { bad++; console.log('find', JSON.stringify(t), got, 'want', want); }
}
console.log(`${all.length} names, ${cases.length} dare cases: ${bad ? bad + ' mismatches' : 'parity ok'}`);
process.exit(bad ? 1 : 0);
