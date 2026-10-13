# topsis_functions.R
# Helper functions for the block-request priority engine.
# All scores use a 1-9 scale where a HIGHER score = HIGHER priority to grant.

# ---- Score for requested duration (hours) -----------------------------------
# DEFAULT POLICY: shorter blocks are easier to grant, so they score higher.
# If your policy is the opposite (longer = higher priority), reverse the y values.
duration_score <- function(hours) {
  approx(x = c(1, 2, 4, 8, 12),
         y = c(9, 8, 6, 3, 1),
         xout = hours, rule = 2)$y
}

# ---- Score for deadline criticality (days until the requested date) ---------
# 0 or negative days (today / overdue) gets the maximum score.
deadline_score <- function(days_left) {
  approx(x = c(0, 1, 3, 7, 15, 30),
         y = c(9, 9, 8, 6, 3, 1),
         xout = days_left, rule = 2)$y
}

# ---- TOPSIS on a fixed 1-9 scale --------------------------------------------
# scores : matrix, one row per request, one column per criterion (all benefit)
# w      : criteria weights from AHP, in the same column order
# Each request's closeness depends only on its own scores and the weights,
# not on which other requests are in the pool.
topsis_fixed <- function(scores, w, smax = 9, smin = 1) {
  V  <- sweep(scores / smax, 2, w, "*")      # weighted normalized matrix
  Ap <- w * 1                                # ideal solution      (all scores = smax)
  Am <- w * (smin / smax)                    # anti-ideal solution (all scores = smin)
  Dp <- sqrt(rowSums(sweep(V, 2, Ap)^2))     # distance to ideal
  Dm <- sqrt(rowSums(sweep(V, 2, Am)^2))     # distance to anti-ideal
  Dm / (Dp + Dm)                             # closeness coefficient (0..1)
}

# ---- Classic pool-based TOPSIS, for cross-checking against a package ---------
topsis_classic <- function(X, w) {
  R  <- sweep(X, 2, sqrt(colSums(X^2)), "/")
  V  <- sweep(R, 2, w, "*")
  Ap <- apply(V, 2, max)
  Am <- apply(V, 2, min)
  Dp <- sqrt(rowSums(sweep(V, 2, Ap)^2))
  Dm <- sqrt(rowSums(sweep(V, 2, Am)^2))
  Dm / (Dp + Dm)
}
