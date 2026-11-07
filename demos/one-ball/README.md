# One-ball animation demo

A test of what a single delivery could look like in a phone game built on this engine. It is a standalone page: no backend, no engine calls, one fixed delivery.

**Run it:** open `index.html` in a browser. On a laptop, use the browser's phone view (DevTools → device toolbar) to see the portrait layout.

## What it shows (~13 s)

1. A broadcast camera behind the bowler: run-up, delivery at 143.6 km/h, the ball pitching.
2. The batter lofts it for six. The camera follows the ball into the crowd, then fireworks, flashing LED boards, and the score updates.
3. A close-up of the batter celebrating.
4. A quarter-speed replay from beside the batter, with the ball's path, the spot where it pitched, and release, length and speed-off-the-bat stats.
5. An end card with "Watch again".

Sound (bat crack, crowd, fireworks) stays off until you press the button. With `prefers-reduced-motion` turned on, it shows a still frame at the moment of contact.

## How it's built

- Everything is drawn in a single `<canvas>` with plain JavaScript, with no libraries and no images or video. The fonts load from Google Fonts.
- A small 3D projection with cameras that move, players built from jointed skeletons, keyframed poses for the batter and bowler, and a ball on real projectile paths (release → bounce → bat → landing spot).
- Team names, players and scores are fictional.

## Linking it to the engine

Each ball the engine simulates could choose the shot animation, line, length and landing spot. The engine's `highlight.js` already models length, direction and field positions. The engine decides what happens on each ball, and the animation only shows it.

Tip: append `#t=6.5` to the URL to pause on a given second.
