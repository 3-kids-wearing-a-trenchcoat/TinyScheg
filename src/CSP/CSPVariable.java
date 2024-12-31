package CSP;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;

import CSP.Exceptions.VariableAssignmentException;
import Scheduler.*;

public class CSPVariable {
    private final Shift shift;   // The shift represented by this variable
    private HashSet<Worker> domain; // The domain for this variable
    private final HashSet<CSPConstraint> constraints; // Constraints going from this variable to another
    private Worker assigned = null; // The worker assigned to this node.

    // Variables used for assessment functions
//    private final Double expectedRatio; // expected ratio between time in this shift and rest following it
    private static HashMap<Shift, Double> expectedRatio; // map between shift and its expected ratio
    private Double trueRatio = Double.POSITIVE_INFINITY; // True ratio between time in this shift and rest following it.
                                                         // Infinity indicates that this is the last shift.
//    private CSP.CSPVariable previousShift = null; // previous shift assigned to the same worker.
//    private CSP.CSPVariable nextShift = null; // next shift assigned to the same worker.
//    // Maintaining these two pointers will spare us the need to scan all shifts when making adjustments on workload
//    // or spread shifts out assessment functions.

    public CSPVariable(Shift shift, List<Worker> workers, HashSet<CSPConstraint> constraints){
        this.shift = shift;
        this.domain = new HashSet<Worker>(workers);
        this.constraints = constraints;
    }

    private CSPVariable(CSPVariable original, Worker assigned){
        this.shift = original.shift;
        this.domain = (HashSet<Worker>) original.domain.clone();
        this.constraints = original.constraints;
        this.trueRatio = original.trueRatio;
        this.assigned = assigned;
    }

    public HashSet<Worker> getDomain() {return this.domain;}
    public Shift getShift() {return shift;}
    public HashSet<CSPConstraint> getConstraints() {return constraints;}
    public Worker getAssigned() {return assigned;}
    public void setTrueRatio(Double trueRatio) {this.trueRatio = trueRatio;}
    public Double getTrueRatio() {return trueRatio;}

    public CSPVariable assign(Worker value) throws VariableAssignmentException{
        if (!domain.contains(value)){
            throw new VariableAssignmentException("Tried to assign value not in domain.");
        }
        if (this.assigned != null) {
            throw new VariableAssignmentException("Attempted to assign a value to a variable which already has a value" +
                    " assigned to it.");
        }

        CSPVariable output = new CSPVariable(this, value);
        // TODO: this would probably be a good place to update trueRatio and pointers if I choose to implement them.

        return output;
    }

}
