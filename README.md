# An Algebraic Adventure

A 2D educational role-playing game (RPG) built in Python with **Pygame**, designed to help middle school students build fluency in foundational algebra through interactive exploration, puzzle-solving, and turn-based combat.

---

## Overview

**An Algebraic Adventure** transforms traditional algebra practice into an engaging dungeon-and-overworld adventure. Instead of static worksheets, players progress through quests, unlock areas, and defeat enemies by solving dynamically generated algebraic equations and expressions.

Originally developed as a high school computer science project, this repository showcases object-oriented game architecture, state management, tile-based movement, and procedural math problem generation.

### Educational Concepts Covered
- **Order of Operations (PEMDAS):** Evaluating multi-step numerical expressions.
- **One-Step & Two-Step Linear Equations:** Solving for unknown variables (e.g., $2x + 5 = 17$).
- **Variables & Substitution:** Evaluating algebraic expressions for given variable values.
- **Inequalities & Ratios:** Applying proportional reasoning and comparison logic in boss encounters.

---

## Features

- **Turn-Based Math Combat:** Attack accuracy, damage multipliers, and defensive shields scale with the player's speed and accuracy in solving algebra problems.
- **Progressive Difficulty:** Enemy encounters dynamically adjust equation complexity based on the current zone or player level.
- **2D World Exploration:** Top-down movement, collision detection, NPC dialogue, and interactive checkpoints.
- **Object-Oriented Architecture:** Modular separation between the game loop, entity sprites, UI overlays, and the procedural math problem engine.

---

## Repository Structure

```text
An_Algebraic_Adventure/
├── assets/               # Sprites, tilesets, fonts, and audio files
├── src/                  # Core game logic, entities, states, and math engine
├── main.py               # Entry point to launch the game
├── requirements.txt      # Python dependencies (pygame)
└── README.md
```
*(Adjust directory names above if your local file layout differs.)*

---

## Getting Started

### Prerequisites
- Python 3.8+
- `pygame`

### Installation
```bash
git clone [https://github.com/mihirvc19/An_Algebraic_Adventure.git](https://github.com/mihirvc19/An_Algebraic_Adventure.git)
cd An_Algebraic_Adventure
pip install -r requirements.txt
```

### Running the Game
```bash
python main.py
```

---

## Controls

| Key | Action |
| :--- | :--- |
| **W A S D** / **Arrow Keys** | Move character |
| **Enter** / **Space** | Interact with NPCs / Confirm answer |
| **0–9**, **`-`**, **Backspace** | Input numerical solutions during encounters |
| **Esc** | Pause menu / Quit |

---

## Future Improvements

- [ ] Add multi-step equations with variables on both sides and basic graphing challenges.
- [ ] Implement persistent save files (`JSON`) to track student progress and accuracy statistics across sessions.
- [ ] Package standalone executables via `PyInstaller` for classroom deployment without requiring Python setup.

---

## License

This project is open-source and available under the [MIT License](LICENSE).
