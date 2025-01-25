package CSP;

import Scheduler.Shift;
import Scheduler.Worker;

import java.util.TreeSet;

public class AssessorWorker implements Cloneable{
    private final Worker worker; // The worker this Assessor represents
    private final TreeSet<Shift> assigned = new TreeSet<>(); // shifts assigned to this worker
    private double currentScore = 0;

    public AssessorWorker(Worker worker) {
        this.worker = worker;
        // TODO: implement
    }
}
