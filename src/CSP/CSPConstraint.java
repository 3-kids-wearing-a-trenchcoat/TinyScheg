package CSP;

import java.util.Objects;

public abstract class CSPConstraint {
    protected final CSPVariable from;
    protected final CSPVariable to;

    public CSPConstraint(CSPVariable from, CSPVariable to){
        this.from = from;
        this.to = to;
    }

    /**
     * Apply arc-consistency to the domain of the "to" variable based on "from"'s assignment
     * @return The number of elements removed for the domains of the variables as a result of making it arc consistent.
     *         Obviously, if it returns 0 it means there has been no change.
     */
    public abstract int makeArcConsistent();

    public abstract CSPConstraint mapClone(CSPVariable from, CSPVariable to);

    public CSPVariable getFrom() {return from;}
    public CSPVariable getTo() {return to;}

    @Override
    public boolean equals(Object obj){
        if (obj == null) {return false;}
        // same kind of constraint
        if (!this.getClass().equals(obj.getClass())) {return false;}
        // same to and from
        CSPConstraint other = (CSPConstraint) obj;
        return this.to.equals(other.to) && this.from.equals(other.from);
    }

    @Override
    public int hashCode(){
        return Objects.hash(from, to);
    }
}

