package CSP;

import java.util.HashMap;
import java.util.HashSet;
import Scheduler.*;

public abstract class CSPConstraint {
    protected final CSPVariable from;
    protected final CSPVariable to;

    public CSPConstraint(CSPVariable from, CSPVariable to){
        this.from = from;
        this.to = to;
    }

    public abstract HashSet<Worker> getArcConsistentDomain();
    public abstract HashSet<Worker> getArcConsistentDomain(HashMap<CSPVariable, CSPVariable> alias);
}

