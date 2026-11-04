# ADR 0011 — King of the hill: five kings per profile, 20% each

**Status:** accepted, 2026-10-26; the shares are amended by ADR 0013 (King #1 holds the share of every
empty slot). Owner decision.

**Context.** Each profile paid its whole miner allocation to one champion until a challenger beat it by the
margin (winner-take-all). A champion that was dethroned stopped earning at once, however recent its win.

**Decision.**
- Each profile keeps a queue of five kings. King #1 is the current champion, the stack every challenger must
  beat. The replacement rule, margin and checks are unchanged.
- A challenger that beats King #1 becomes the new King #1, every king moves down one place, and King #5
  leaves the queue and is no longer paid.
- Each slot earns 20% of the profile's miner allocation. The share of an empty slot goes to the owner UID,
  which the chain burns: with only the tuned baseline the whole allocation burns, and with one king 20% is
  paid and 80% burns.
- A king that is suspended, retired, excluded or not registered at publication keeps its place, and its
  share burns. A rolled-back king leaves the queue, and the kings below it move up.
- The queue is read from the champion history (`select_kings`), so no table or migration is needed. The
  number of slots is `KING_SLOTS = 5` in `ramcove_protocol.weights`.

**Consequences.** A win keeps paying for four more crownings after it is beaten, so a strong result earns
for longer and a runner-up that was crowned earlier is still rewarded. One hotkey that crowned two stacks
holds two slots. Until five kings exist, part of the allocation burns, and the weight writer stays disabled
until the burn mechanism is verified on a testnet, as before.
