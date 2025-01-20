package CSP;

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
}

