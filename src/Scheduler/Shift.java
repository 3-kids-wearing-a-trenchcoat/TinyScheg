package Scheduler;

import java.time.LocalDateTime;
import java.util.Vector;

public class Shift implements Comparable<Shift>, Cloneable{
    private final String name;
    private final LocalDateTimeRange timeRange;
    private final int workerNum;
    private String type = null;
    // TODO: change to support multiple types
    private Vector<Worker> assigned = new Vector<Worker>();

    public Shift(String name, LocalDateTimeRange timeRange, int workerNum){
        this.name=name;
        this.timeRange = timeRange;
        this.workerNum = workerNum;
    }
    public Shift(String name, LocalDateTimeRange timeRange, int workerNum, String role){
        this.name=name;
        this.timeRange = timeRange;
        this.workerNum = workerNum;
        this.type = role;
    }

    public String getName() {return name;}
    public LocalDateTimeRange getTimeRange() {return timeRange;}
    public int getWorkerNum() {return workerNum;}
    public String getType() {return type;}
    public Vector<Worker> getAssigned() {return assigned;}
    public void setType(String type) {this.type = type;}

    public void assign(Worker worker) throws ArrayIndexOutOfBoundsException{
        if(assigned.size() == workerNum) {throw new ArrayIndexOutOfBoundsException("no more unassigned spaces");}
        //TODO: when roles are implemented, this is where a check would go.
        assigned.add(worker);
        worker.setLastShift(timeRange.getEnd());
    }
    public void unassign(Worker worker) {assigned.remove(worker);}

    public int getAssignedNum() {return assigned.size();}

    public LocalDateTime getStart() {return timeRange.getStart();}
    public LocalDateTime getEnd() {return timeRange.getEnd();}

    /**
     * Compare according to time range.
     * If equal, compare names lexicographically.
     * @param other the object to be compared.
     * @return
     */
    @Override
    public int compareTo(Shift other){
//        return timeRange.compareTo(other.timeRange);
        int rangeComparison = timeRange.compareTo(other.timeRange);
        if (rangeComparison == 0) {return name.compareTo(other.name);}
        return rangeComparison;
    }

    @Override
    public boolean equals(Object obj){
        if(!(obj instanceof Shift)) return false;
        Shift other = (Shift) obj;
//        return name.equals(other.name) && timeRange.equals(other.timeRange) && workerNum == other.workerNum &&
//                type.equals(other.type) && assigned.equals(other.assigned);
        return name.equals(other.name) && timeRange.equals((other.timeRange));
    }

    @Override
    public Shift clone() throws CloneNotSupportedException {
        Shift output;
        try {output = (Shift) super.clone();}
        catch (CloneNotSupportedException e) {throw new CloneNotSupportedException("Something impossible happened.");}
        output.assigned = new Vector<Worker>(assigned);
        return output;
    }

    @Override
    public String toString() {
        String output = name + " (" + timeRange.toString() + ") \n =====";
        for (Worker worker : assigned){
            output += worker.toString();
            output += "   ";
        }
        output += "=====";
        return output;
    }

    public String getAssignedString(){
        String output = "";
        for (Worker worker : assigned){
            output += worker.getName();
            if(!assigned.getLast().equals(worker)) output += " & ";
        }
        return output;
    }

    /**
     * Check if the input worker fits this shift type.
     * The current implementation is that if the shift type is null it is open to all workers.
     * Otherwise, the worker's role must match the shift's type.
     * @param worker
     * @return 'true' if worker's role fits this shift's type, 'false' otherwise
     */
    public boolean fitsRole(Worker worker){
        return type == null || type.equals(worker.getRole());
    }
}
