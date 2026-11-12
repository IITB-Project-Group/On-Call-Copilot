# On-Call Copilot — slides

**PowerPoint deck (11 slides):** [`submission/On-Call-Copilot-Slides.pptx`](submission/On-Call-Copilot-Slides.pptx)  
**GitHub:** https://github.com/IITB-Project-Group/On-Call-Copilot/blob/main/docs/submission/On-Call-Copilot-Slides.pptx  

Supporting detail: [ARCHITECTURE.md](ARCHITECTURE.md) · [agents/evaluation.md](agents/evaluation.md) · Demo `Demo/video1909353936.mp4`.

---

## Deck contents

1. **Title** — On-Call Copilot · team (R2–R6) · repo  
2. **Problem & user** — on-call engineer · alert → approve → verify · `./up.sh`  
3. **Architecture** — Alertmanager → API → guardrails → graph → approval → memory  
4. **Multi-agent graph (C2)** — commander · triage · parallel diagnosis · approve · verify · learn  
5. **Diagnosis as planning** — typed hypotheses · budgeted evidence · replan on contradiction  
6. **Safe action** — no shell · allow-listed writes · exact-command approval · verify/rollback  
7. **Memory & playbook** — preconditions · freeze · pm-006 rejected on payment incident  
8. **Security** — T1–T10 · log injection blocked · oncall-security reports  
9. **Evaluation** — twin E1/E4 numbers · harmful executed = 0 · held-out still open  
10. **Demo & links** — video + doc map + portal PDF  
11. **Limits & next** — Reflexion freeze · held-out ×3 · equal-model ablation  

Open `docs/submission/On-Call-Copilot-Slides.pptx` in PowerPoint or Keynote.
