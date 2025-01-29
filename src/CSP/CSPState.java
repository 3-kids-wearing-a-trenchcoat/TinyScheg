package CSP;

import CSP.Exceptions.VariableAssignmentException;
import CSP.Exceptions.WeightException;
import Scheduler.Shift;
import Scheduler.Worker;

import java.util.*;
import java.util.concurrent.*;

public class CSPState implements Comparable<CSPState>, Runnable{
    private static final int MIN_REST = 3; // minimum time between shifts (in hours)
    private static final int POOL_SIZE = 8; // number of concurrent threads that should run
    private static final OutputTracker tracker = new OutputTracker();

//    private static final ExecutorService executorService = Executors.newFixedThreadPool(POOL_SIZE);
    private static final ThreadPoolExecutor executor =
        new ThreadPoolExecutor(POOL_SIZE, POOL_SIZE,
        0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<>(0), Executors.defaultThreadFactory(),
        new RejectedExecutionHandler() {
            @Override
            public void rejectedExecution(Runnable r, ThreadPoolExecutor executor) {
                r.run(); // if max number of threads, run the next child state in the same thread as the parent.
            }
        });

    private TreeSet<CSPVariable> variables;
    private Assessor assessor;
    private int possibleAssignments = 0;
    private boolean satisfiable = true; // if 'false', this state cannot be satisfied and can be pruned.

    public CSPState(List<Shift> shifts, List<Worker> workers){
        // Create a temporary TreeSet which will have the same items as variables, ordered by shift period.
        // This will make applying the Different constraints quicker.
        TreeSet<CSPVariable> variablesOrderedByShift = new TreeSet<>((s1, s2) -> s1.getShift().compareTo(s2.getShift()));

        // Generate variables, constraints will come later.
        for (Shift shift : shifts){
            List<Worker> domain = unaryConstraints(shift, workers); // starting domain of the shift
            // create all CSPVariables for this shift
            ArrayList<CSPVariable> newVars = new ArrayList<>();
            for (int i = 0; i < shift.getWorkerNum(); i++){
                newVars.add(new CSPVariable(shift, domain));
            }
            possibleAssignments += domain.size() * shift.getWorkerNum(); // update possible assignments
            // set equivalence for each CSPVariable
            for (CSPVariable newVar : newVars){
                newVar.setEquivalentVariables(subsetExcluding(newVars, newVar));
            }
            // add new Variables for this shift to the TreeSet of variables
            variables.addAll(newVars);
            variablesOrderedByShift.addAll(newVars);
        }

        // Generate all 'Different' constraints for the variables
        for (CSPVariable var : variablesOrderedByShift){ // go through all variables
            // compare with all variables that come AFTER this variable
            for (CSPVariable otherVar : variablesOrderedByShift.tailSet(var, false)){
                // If this variable's shift is within MIN_REST hours of the other variable's shift
                if (var.getShift().getTimeRange().overlaps(otherVar.getShift().getTimeRange(), MIN_REST)){
                    var.addConstraint(new Different(var, otherVar)); // constrain the two variables to be different
                    otherVar.addConstraint(new Different(otherVar, var));
                    // This should also affect the variables in variables, since they are pointers to the same object.
                }
                else{
                    // If we encounter an otherVar that is not within MIN_REST hours, we can conclude from
                    // variablesOrderedByShift's ordering that all subsequent otherVars will also be outside this range.
                    // That is because we scan through the tailSet, meaning all otherVars we scan will have a shift time
                    // equal or later than that of var.
                    break;
                }
            }
        }
    }

//    /**
//     * Base constructor, The Assessor's weights will be set to their default values.
//     * @param variables A list of CSPVariables representing the shifts to be assigned.
//     */
//    public CSPState(List<CSPVariable> variables){
//        this.variables = new TreeSet<CSPVariable>(variables);
//        for (CSPVariable variable: variables){
//            possibleAssignments += variable.getDomain().size();
//        }
////        assessor = new Assessor();
//        assessor = new Assessor(this);
//    }

//    /**
//     * Explicitly set the Assessor's weights
//     * @param variables A list of CSPVariables representing the shifts to be assigned.
//     * @param weights a list of weights to be applied to the assessment functions. (must match number of funcs)
//     */
//    public CSPState(List<CSPVariable> variables, List<Double> weights) throws WeightException {
//        this.variables = new TreeSet<CSPVariable>(variables);
//        for (CSPVariable variable: variables){
//            possibleAssignments += variable.getDomain().size();
//        }
////        assessor = new Assessor(weights);
//        assessor = new Assessor(this, weights);
//    }

    /**
     * The copy constructor, used to create an independent clone of the old constructor.
     * Will be called by a parent state when creating new states via assignment
     * @param old The parent CSPState
     * @param variable The variable to be assigned
     * @param value The value to assign to the variable
     * @throws VariableAssignmentException If the variable has already been assigned or if it's not in the domain.
     */
    public CSPState(CSPState old, CSPVariable variable, Worker value) throws VariableAssignmentException {
        variables = new TreeSet<>();
        assessor = old.assessor.clone();

        // generate clone variables and map the old variables to their clone
        HashMap<CSPVariable, CSPVariable> variableMap = new HashMap<>();
        for (CSPVariable oldVariable: old.variables){
            variableMap.put(oldVariable, oldVariable.clone());
        }
        // Fix the new variables so that their constraints point at the new variables, and add to 'variables'
        for (CSPVariable newVariable : variableMap.values()){
            newVariable.mapConstraints(variableMap);
            variables.add(newVariable);
        }
        // apply assignment and update 'satisfiable' and 'possibleAssignments' accordingly.
        int removed = variableMap.get(variable).assign(value);
        if (removed == -1) {
            satisfiable = false;
            return;
        }
        possibleAssignments -= removed;
        assessor.recalculate(this, variable, value); // recalculate the state's score following the assignment
    }

    @Override
    public int compareTo(CSPState other){
        // THIS IMPLEMENTATION IS NOT CONSISTENT WITH EQUALS OR HASHCODE! But it should be fine (FLW)
        return Integer.compare(possibleAssignments, other.possibleAssignments);
    }

    @Override
    public void run(){
        // If this is not a new state, stop this run.
        // If it IS a new state, tracker will be updated.
        if (!tracker.checkNew(this)) {return;}

        for (CSPVariable var : variables){ // go through all variables in order
            TreeSet<CSPState> children = new TreeSet<>(); // Generate list of children to run next
            for (Worker value : var.getDomain()){ // for every value in the domain of this variable
                try {
                    CSPState child = new CSPState(this, var, value); // generate new child
                    if (!child.satisfiable || !tracker.checkScore(child)){
                        continue; // If child is unsatisfiable or its score is below the candidate
                    }
                    // if child is a complete assignment, check if it's the best so far.
                    if (child.isComplete()) {tracker.nominate(child);}
                    else {children.add(child);}
                }
                catch (VariableAssignmentException e) {throw new RuntimeException(e);}

                for (CSPState child : children){
                    executor.execute(child);
                }
            }
        }
    }

    @Override
    public boolean equals(Object obj){
        if (!(obj instanceof CSPState)) {return false;}
        CSPState other = (CSPState) obj;
        return variables.equals(other.variables);
    }

    @Override
    public int hashCode(){
        return Objects.hash(variables);
    }

    public double getScore() {return assessor.getScore();}

//    public boolean isComplete() {return possibleAssignments == 0 && satisfiable;}
    public boolean isComplete() {return possibleAssignments == 0;}

    public boolean isSatisfiable() {return satisfiable;}

    private List<Worker> unaryConstraints(Shift shift, List<Worker> workers){
        List<Worker> output = new ArrayList<>();
        for (Worker worker : workers){
            if (worker.isAvailable(shift, false)){  // must be available during this time
                // must match role, may need to reconsider this implementation when I support multiple roles
                if (shift.fitsRole(worker)) {output.add(worker);} // fits unary constraints, add to output.
            }
        }

        return output;
    }

//    private ArrayList<Worker> subsetExcluding(ArrayList<Worker> inputList, Worker toRemove){
//        ArrayList<Worker> output = (ArrayList<Worker>) inputList.clone();
//        output.remove(toRemove);
//        return output;
//    }
    private ArrayList<CSPVariable> subsetExcluding(ArrayList<CSPVariable> inputList, CSPVariable toRemove){
        ArrayList<CSPVariable> output = (ArrayList<CSPVariable>) inputList.clone();
        output.remove(toRemove);
        return output;
    }
}
