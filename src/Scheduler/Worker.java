package Scheduler;

import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.Objects;
import java.util.PriorityQueue;

public class Worker implements Comparable<Worker>, Cloneable{
    private static final LocalDateTime  DEFAULT_LAST_SHIFT = LocalDateTime.of(2020, 1, 1, 0, 0);

    private final String name;
    private String role;
    private PriorityQueue<LocalDateTimeRange> unavailable = new PriorityQueue<>();
    private HashSet<Worker> likeList = new HashSet<>();
    private HashSet<Worker> dislikeList = new HashSet<>();
    private LocalDateTime lastShift;

    public Worker(String name) {
        this.name=name;
        this.role = null;
        lastShift = DEFAULT_LAST_SHIFT;
    }
    public Worker(String name, String role) {
        this.name = name;
        this.role = role;
        lastShift = DEFAULT_LAST_SHIFT;
    }
    public Worker(String name, LocalDateTime lastShift){
        this.name = name;
        this.role = null;
        if (lastShift == null) lastShift = DEFAULT_LAST_SHIFT;
        else this.lastShift = lastShift;
    }
    public Worker(String name, String role, LocalDateTime lastShift){
        this.name = name;
        this.role = role;
        if (lastShift == null) this.lastShift = DEFAULT_LAST_SHIFT;
        else this.lastShift = lastShift;
    }

    public void setRole(String role) {this.role = role;}
    public String getRole() {return role;}
    public String getName() {return name;}

    public PriorityQueue<LocalDateTimeRange> getUnavailable() {return unavailable;}

    /**
     * Sets the Scheduler.Worker as unavailable during the given range.
     * If the given range overlaps with an existing range in which this Scheduler.Worker is unavailable,
     * the two will be merged.
     * @param range Scheduler.LocalDateTimeRange specifying the period in which this Scheduler.Worker is unavailable.
     */
    public void addUnavailable(LocalDateTimeRange range) {
        if (range == null) return;
        // Check if the given range overlaps with an existing range, if so, merge them.
        for (LocalDateTimeRange existingRange : unavailable){
            if (range.overlaps(existingRange)){
                LocalDateTimeRange newRange = LocalDateTimeRange.merge(range, existingRange);
                unavailable.remove(existingRange);
                unavailable.add(newRange);
                return;
            }
        }

        unavailable.add(range);
    }
    public void removeUnavailable(LocalDateTimeRange range) {unavailable.remove(range);}

    /**
     * Checks if this worker is available in a given Scheduler.LocalDateTimeRange.
     * Meaning, the given range does not overlap with a Scheduler.LocalDateTimeRange in which
     * this Scheduler.Worker is unavailable.
     * if the variable 'remove' is set to 'True',
     * any period in time in which this Scheduler.Worker is unavailable and ends before the given range will be removed.
     * @param range Range to check
     * @param remove Whether to remove unavailable DateTime ranges which passed.
     * @return 'True' if this Scheduler.Worker is available at the given range, 'False' otherwise.
     */
    public boolean isAvailable(LocalDateTimeRange range, boolean remove){
        if (remove) { // remove any expired unavailability range we encounter
            while (true) {
                if (unavailable.isEmpty()) return true;
                LocalDateTimeRange currentUnavailable = unavailable.peek();
                if (currentUnavailable.overlaps(range)) return false;
                // does not overlap
                if (currentUnavailable.isAfter(range)) return true;
                // does not overlap and is before the soonest unavailability,
                // which means so are subsequent unavailability ranges.
                else {unavailable.poll();} // does not overlap but this unavailability range is before the given range,
                // meaning a subsequent range MIGHT overlap with the given range, therefor loop must continue.
            }
        }

        else { // leave the unavailable Queue intact while checking
            for (LocalDateTimeRange currentUnavailable : unavailable){
                if (currentUnavailable.overlaps(range)) return false;
            }
            return true;
        }
    }
    public boolean isAvailable(Shift shift, boolean remove) {return isAvailable(shift.getTimeRange(), remove);}

    public boolean likes(Worker worker) {return likeList.contains(worker);}
    public boolean dislikes(Worker worker) {return dislikeList.contains(worker);}
    public void addLiked(Worker worker) {likeList.add(worker);}
    public void addDisliked(Worker worker) {dislikeList.add(worker);}
    public void removeLiked(Worker worker) {likeList.remove(worker);}
    public void removeDisliked(Worker worker) {dislikeList.remove(worker);}

    public void setLastShift(LocalDateTime time) {lastShift = time;}
    public LocalDateTime getLastShift() {return lastShift;}

    @Override
    public boolean equals(Object obj){
        if (!(obj instanceof Worker)) return false;
        Worker other = (Worker) obj;
        return name.equals(other.name); // It might be a bit optimistic, but it fits my needs.
    }

    @Override
    public int hashCode(){
        // May be a bit too simplistic but seems to get the job done.
        return Objects.hashCode(name);
    }

    @Override
    public Worker clone() throws CloneNotSupportedException{
        Worker output;
        try {output = (Worker) super.clone();}
        catch (CloneNotSupportedException e) {throw new CloneNotSupportedException("Something impossible happened.");}
        output.unavailable = new PriorityQueue<>(unavailable);
        output.likeList = new HashSet<Worker>(likeList);
        output.dislikeList = new HashSet<Worker>(dislikeList);
        return output;
    }

    @Override
    public int compareTo(Worker other) {
        if (lastShift.isBefore(other.lastShift)) return -1;
        if (lastShift.isAfter(other.lastShift)) return 1;
        return 0;
    }

    @Override
    public String toString() {return name;}
}
