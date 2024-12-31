package CSP;

import Scheduler.*;
import java.util.HashMap;
import java.util.HashSet;

public class Different extends CSPConstraint{
    public Different(CSPVariable from, CSPVariable to) {
        super(from, to);
    }

    /**
     * Generate a new domain for the "from" variable which is arc consistent.
     * @return a subset of The "from" domain of all values that have at least one value in the "to" domain
     * that is different to them.
     */
    public HashSet<Worker> getArcConsistentDomain(){
        HashSet<Worker> fromDomain = from.getDomain();
        HashSet<Worker> toDomain = to.getDomain();
        
        return findDomain(fromDomain, toDomain);
    }

    /**
     * Generate a new domain for the "from" variable which is arc consistent.
     * @param alias A mapping between the 'original' worker (as was created at the start of the algorithm's run)
     *              and its 'alias'.
     * @return a subset of The "from" domain of all values that have at least one value in the "to" domain
     * that is different to them.
     */
    public HashSet<Worker> getArcConsistentDomain(HashMap<CSPVariable, CSPVariable> alias){
        HashSet<Worker> fromDomain = alias.get(from).getDomain();
        HashSet<Worker> toDomain = alias.get(to).getDomain();

        return findDomain(fromDomain, toDomain);
    }
    
    private HashSet<Worker> findDomain(HashSet<Worker> fromDomain, HashSet<Worker> toDomain){
        HashSet<Worker> output = new HashSet<Worker>();

        for (Worker value : fromDomain){
            for (Worker potentialAssignment : toDomain){
                if (!value.equals(potentialAssignment)){
                    output.add(value);
                    break;
                }
            }
        }

        return output;
    }
}
