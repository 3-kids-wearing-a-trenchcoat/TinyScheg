package CSP;

import Scheduler.*;
import java.util.HashMap;
import java.util.HashSet;

public class Different extends CSPConstraint{
    public Different(CSPVariable from, CSPVariable to) {
        super(from, to);
    }

    /**
     * Change the domain of the "to" variable to make it arc-consistent.
     * Specifically, If from's assigned worker is in to's domain, remove that worker.
     * @return 1 if a worker has been removed from to's domain, 0 otherwise.
     */
    public int makeArcConsistent(){
        Worker value = from.getAssigned();
        if (value == null || to.getAssigned() != null) {return 0;}
//      // If no worker is assigned to the 'from' variable or a worker is already assigned to the 'to' variable.
        return (to.getDomain().remove(value) ? 1 : 0); // return 1 if value was previously in domain, 0 otherwise.
    }
//    public boolean makeArcConsistent(){
//        Worker value = from.getAssigned();
//        if (value == null || to.getAssigned() != null) {return false;}
//        // If no worker is assigned to the 'from' variable or a worker is already assigned to the 'to' variable.
//        return to.getDomain().remove(value); // returns 'true' if value was previously in the domain.
//    }

    public CSPConstraint mapClone(CSPVariable from, CSPVariable to){
        return new Different(from, to);
    }
}
