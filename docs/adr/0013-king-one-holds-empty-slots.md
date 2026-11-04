# ADR 0013 — King #1 holds the share of every empty slot

**Status:** accepted, 2026-11-04. Owner decision; amends the shares in ADR 0011.

**Context.** Under ADR 0011 each of the five king slots earned 20% of the profile's miner allocation and the
share of an empty slot burned. The first winner earned 20% while 80% burned, and the allocation
was fully paid only once five kings existed.

**Decision.**
- Each king below King #1 earns one equal share, 20% of the profile's miner allocation.
- King #1, the current champion, earns the rest: its own 20%, the share of every empty slot and any rounding
  remainder. As the queue fills the shares are 100%; 80/20; 60/20/20; 40/20/20/20; and 20% each.
- With only the tuned baseline there is no king, and the whole allocation is proposed for the owner UID,
  which the chain burns. A king that is suspended, retired, excluded or not registered keeps its place and its
  share burns, as before; when that king is King #1, the empty slots' shares burn with it.
- One pure function, `slot_shares` in `ramcove_protocol.weights`, gives each slot's share. The weight plan,
  the signed weight result and the dashboard all use it.

**Consequences.** From the first win onward nothing burns while every king is eligible and registered, so the
weight writer no longer waits for the burn mechanism once a king exists. The first king earns the whole
allocation until the next win, which rewards the first real improvement over the tuned baseline strongly.
Each further king below King #1 lowers King #1's share by 20% until the queue is full.
