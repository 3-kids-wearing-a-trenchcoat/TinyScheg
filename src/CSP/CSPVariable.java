package CSP;

import java.util.*;

import CSP.Exceptions.VariableAssignmentException;
import Scheduler.*;

/**
 * CSPVariable represents a variable in a CSP problem.
 * In our particular case CSPVariable represents a slot in a shift we would like to assign a worker to.
 * We will treat this object as mutable.
 */
public class CSPVariable implements Cloneable, Comparable<CSPVariable>{
    private final Shift shift;   // The shift represented by this variable
    private HashSet<Worker> domain; // The domain for this variable
    // TODO: Change the data structure to support ordered
    private HashSet<CSPConstraint> constraints; // Constraints going from this variable to another
    private Worker assigned = null; // The worker assigned to this node.

    // Variables used for assessment functions
//    private final Double expectedRatio; // expected ratio between time in this shift and rest following it
    private static HashMap<Shift, Double> expectedRatio; // map between shift and its expected ratio
    private Double trueRatio = Double.POSITIVE_INFINITY; // True ratio between time in this shift and rest following it.
                                                         // Infinity indicates that this is the last shift.

    public CSPVariable(Shift shift, List<Worker> workers, HashSet<CSPConstraint> constraints){
        this.shift = shift;
        this.domain = new HashSet<Worker>(workers);
        this.constraints = constraints;
    }

    public HashSet<Worker> getDomain() {return this.domain;}
    public Shift getShift() {return shift;}
    public HashSet<CSPConstraint> getConstraints() {return constraints;}
    public Worker getAssigned() {return assigned;}
    public boolean isAssigned() {return assigned != null;}
    public void setTrueRatio(Double trueRatio) {this.trueRatio = trueRatio;}
    public Double getTrueRatio() {return trueRatio;}
    public static void setExpectedRatio(HashMap<Shift, Double> expectedRatio) {
        CSPVariable.expectedRatio = expectedRatio;
    }

    /**
     * Updates the domains of variables that are constrained by this variable according to AC-3.
     * @return If the schedule has become unsatisfiable, -1 is returned.
     *         Otherwise, This method returns the number of assignments removed by this method.
     */
    private int enforceArcConsistency(){
        int removed = 0; // track number of values in the domains which are removed as a result of AC-3

        ArrayDeque<CSPConstraint> queue = new ArrayDeque<>(this.constraints);
        CSPConstraint constraint = queue.poll();

        while (constraint != null){ // for every constraint in the queue.
            int change = constraint.makeArcConsistent();
            if (change != 0) { // If a change was made to variable to's domain
                removed += change;
                CSPVariable to = constraint.getTo();
                queue.addAll(to.getConstraints()); // enforce arc consistency on its constraints as well.

                // If Variable has a domain of size 1, assign it right away.
                if (to.getDomain().size() == 1) {
                    try{
                        removed += to.assign((Worker) to.getDomain().toArray()[0], false);
                    }
                    catch (VariableAssignmentException e) {
                        // We got the only worker from to's domain so this error can't be raised by it.
                        // Likewise, MakeArcConsistent checks would return false if to was assigned.
                        // So this Exception has absolutely no business happening.
                        System.out.println("Some sort of unexpected disaster has occurred in enforceArcConsistency");
                        return -1;
                    }
                }
                else if (to.getDomain().isEmpty()){ // if after the change a domain has been made empty
                    return -1; // This state is unsatisfiable.
                }
            }
            constraint = queue.poll(); // move on to next constraint.
        }
        return removed;
    }

    /**
     * Assigns the given value to this variable.
     * @param value The value to be assigned to this variable.
     * @param enforce Set to 'false' if you want this function to ignore arc consistency.
     *                              Should only be set that way when we assign a variable as part of a running
     *                              Arc Consistency enforcement. (for example when while running enforce
     *                              we encounter a variable with a domain of 1, in which case we auto-assign it.
     * @return 'false' if the assignment resulted in an unsatisfiable schedule, 'true' otherwise.
     * @throws VariableAssignmentException If the variable has already been assigned or if it's not in the domain.
     */
    private int assign(Worker value, boolean enforce) throws VariableAssignmentException{
        if (!domain.contains(value)){
            throw new VariableAssignmentException("Tried to assign value not in domain.");
        }
        if (this.assigned != null) {
            throw new VariableAssignmentException("Attempted to assign a value to a variable which already has a value" +
                    " assigned to it.");
        }

        int removed = domain.size();
        assigned = value;

        if (enforce) {
//            if (!enforceArcConsistency()) {return false;} // unsatisfiable graph
            int removedByArcConsistency = enforceArcConsistency();
            if (removedByArcConsistency == -1) {return -1;} // unsatisfiable graph
            removed += removedByArcConsistency;
        }

        return removed;
    }

    public int assign(Worker value) throws VariableAssignmentException{
        return assign(value, true);
    }

    @Override
    public CSPVariable clone() {
        try {
            CSPVariable clone = (CSPVariable) super.clone();
            return clone;
        } catch (CloneNotSupportedException e) {
            throw new AssertionError();
        }
    }

    /**
     * Count the number of constraints from this variable to an unassigned variable.
     * Used for The Degree Heuristic.
     * @return the number of constrained variables an assignment here would influence.
     */
    private int getNumberOfConstraints(){
        int output = 0;
        for(CSPConstraint constraint : constraints){
            if(constraint.to.assigned == null) {output += 1;}
        }
        return output;
    }

    /**
     * This compareTo implementation is based on the following AC-3 heuristics: (in order)
     * - Minimum Remaining Values (A < B if The size of A's domain is smaller than that of B)
     * - Degree Heuristic (if MRV gives a tie, A < B if the number of constraints A has with unassigned variables is
     *                     GREATER than B)
     *   In addition; an assigned variable always comes after an unassigned variable.
     *   This is to make it easier to tell at a glance in a sorted CSPVariable list whether the schedule is completely
     *   assigned. (a completely assigned schedule would have an assigned variable as its first value)
     * @param other the CSPVariable to be compared.
     * @return -1 if this < other, 1 if this > other, 0 otherwise. (if this == other)
     */
    @Override
    public int compareTo(CSPVariable other) {
        if (isAssigned() != other.isAssigned()) {return this.isAssigned() ? 1 : -1;}

        if (domain.size() == other.domain.size()){ // tie in domain size
            int thisConstraints = getNumberOfConstraints();
            int otherConstraints = other.getNumberOfConstraints();
            // Remember; 1 and -1 are inverted on purpose, we want the more constraining variable to
            // come first in a natural order.
            if (thisConstraints > otherConstraints) {return -1;} // more constrained, this comes before other
            if (thisConstraints < otherConstraints) {return 1;}  // less constrained, this comes after other
            // TODO: If and when I implement LCV, it should go here.
            // If all AC3 heuristics are equal, compare according to shifts and then assigned.
            // This should be more consistent with 'equals'.
            return shiftAssignedComparison(other);
        }

        if (domain.size() < other.domain.size()) {return -1;}
        return 1;
    }

    private int shiftAssignedComparison(CSPVariable other){
        int shiftComparison = shift.compareTo(other.shift);
        if (shiftComparison != 0) {return shiftComparison;}
        // shifts are equal
        if (!isAssigned()){ // if this variable is unassigned
            if (!other.isAssigned()) {return 0;} //both are the same shift and unassigned
            return -1; // unassigned comes before assigned
        }
        return assigned.compareTo(other.assigned); // if both are assigned compare according to worker.
    }

    @Override
    public boolean equals(Object obj){
        if (!(obj instanceof CSPVariable)) {return false;}

        CSPVariable other = (CSPVariable) obj;
        return shift.equals(other.shift) && assigned.equals(other.assigned);
    }

    @Override
    public int hashCode(){
        return Objects.hash(shift, assigned);
    }

    /**
     * Recreate The Variable's constraints according to a map of original variables to their new equivalent.
     * This should be used when CSPState creates a new states and all variables in this new state must be distinct.
     * @param map HashSet where the key is the original variable and the value is the new, equivalent variable.
     */
    protected void mapConstraints(HashMap<CSPVariable, CSPVariable> map){
        HashSet<CSPConstraint> newConstraints = new HashSet<>();

        for (CSPConstraint constraint : constraints){
            CSPVariable newFrom = map.get(constraint.getFrom());
            CSPVariable newTo = map.get(constraint.getTo());
            newConstraints.add(constraint.mapClone(newFrom, newTo));
        }

        constraints = newConstraints;
    }
}
