package CSP;

import java.util.HashSet;

/**
 * This class is used to kep track of which states we have already visited
 * (as to not repeat states we have already checked)
 * As well as keep track of the current output candidate.
 */
public class OutputTracker {
    private final HashSet<CSPState> checked = new HashSet<CSPState>();
    private CSPState candidate = null;
    private double candidateScore = Double.NEGATIVE_INFINITY; // initialized to arbitrarily low score

    /**
     * Check whether the given state is new, if so, add it to the 'checked' set.
     * This is an implementation of the idea that states that were already checked needn't be checked again.
     * @param candidate The CSPState to be checked
     * @return 'true' if this state hadn't been checked before, 'false' if it has.
     */
    public synchronized boolean checkNew(CSPState candidate){
        if (checked.contains(candidate)) {return false;}
        checked.add(candidate);
        return true;
    }

    /**
     * Check whether the given state's score is higher than the current candidate.
     * Since state scores are descending-monotonous, if the score is already lower than the current candidate we
     * can be certain it will not yield a new candidate, and this branch of the search can be pruned.
     * If no candidate exists the candidate score is arbitrarily low, meaning that any state's score is higher
     * than that of a null candidate.
     * @param candidate The CSPState to be checked.
     * @return 'true' if its score is higher than the current candidate, 'false' otherwise.
     */
    public synchronized boolean checkScore(CSPState candidate){
        return candidate.getScore() > candidateScore;
    }

    /**
     * Nominate a CSPState as an output candidate.
     * This method does not verify that this CSPState is actually completely and consistently assigned and assumes it is.
     * If the nominee's score is higher (closer to 0) than that of the current candidate (or if the candidate is null),
     * Replace the existing candidate with the nominee.
     * This method is synchronized and should not allow for race conditions to occur.
     * @param nominee State we nominate to be the output candidate.
     * @return 'true' if the nominee is now the candidate (has lower score), 'false' if the candidate hasn't changed.
     */
    public synchronized boolean nominate(CSPState nominee){
        double nomineeScore = nominee.getScore();
        if (nomineeScore > candidateScore){
            candidate = nominee;
            candidateScore = nomineeScore;
            return true;
        }
        return false;
    }

    public CSPState getCandidate() {return candidate;}
    public double getCandidateScore() {return candidateScore;}
}
