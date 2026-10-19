# 01_weights.R
# Rebuilds the AHP criteria weights from the pairwise judgments in criteria.ahp,
# checks the consistency ratio, and saves data/weights.csv.
# Run this once, and again whenever you change a judgment.

crit <- c("Safety", "Urgency", "Operational", "Deadline", "Duration")
n    <- length(crit)

# The 10 judgments, in this order (same as criteria.ahp):
#  S-U, S-O, S-D, S-Dur,  U-O, U-D, U-Dur,  O-D, O-Dur,  D-Dur
vals <- c(2, 2, 3, 5,
          1, 2, 4,
          2, 4,
          3)

# Build the full reciprocal matrix
A <- diag(n)
k <- 1
for (i in 1:(n - 1)) {
  for (j in (i + 1):n) {
    A[i, j] <- vals[k]
    A[j, i] <- 1 / vals[k]
    k <- k + 1
  }
}
dimnames(A) <- list(crit, crit)

# Eigenvalue method
ev         <- eigen(A)
m          <- which.max(Re(ev$values))
w          <- Re(ev$vectors[, m])
w          <- w / sum(w)
names(w)   <- crit
lambda_max <- Re(ev$values[m])

# Consistency check (random index RI = 1.12 for n = 5)
CI <- (lambda_max - n) / (n - 1)
CR <- CI / 1.12

cat("Criteria weights:\n")
print(round(w, 4))
cat("\nlambda_max =", round(lambda_max, 4),
    " CI =", round(CI, 4),
    " CR =", round(CR, 4),
    ifelse(CR < 0.10, " (acceptable)\n", " (TOO HIGH - revisit judgments)\n"))

# Save for the ranking script
dir.create("data", showWarnings = FALSE)
write.csv(data.frame(criterion = crit, weight = as.numeric(w)),
          "data/weights.csv", row.names = FALSE)
cat("\nSaved data/weights.csv\n")
