package CSP;

import Scheduler.Worker;

import java.util.HashMap;

public class Assessor implements Cloneable{
    private final HashMap<Worker, AssessorWorker> workers = new HashMap<>();

    @Override
    public Assessor clone(){
        // TODO: implement clone
    }
}
