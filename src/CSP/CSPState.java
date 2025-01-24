package CSP;

import CSP.Exceptions.VariableAssignmentException;
import CSP.Exceptions.WeightException;
import Scheduler.Worker;

import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class CSPState implements Comparable<CSPState>, Runnable{
    private static final int POOL_SIZE = 8; // number of concurrent threads that should run
    private static int runningTasks = 0; //number of concurrent threads actually being used


    private static final OutputTracker tracker = new OutputTracker();
    private static final ExecutorService executorService = Executors.newFixedThreadPool(POOL_SIZE);
    private TreeSet<CSPVariable> variables;
    private Assessor assessor;
    private int possibleAssignments = 0;
    private boolean satisfiable = true; // if 'false', this state cannot be satisfied and can be pruned.

    /**
     * Base constructor, The Assessor's weights will be set to their default values.
     * @param variables A list of CSPVariables representing the shifts to be assigned.
     */
    public CSPState(List<CSPVariable> variables){
        this.variables = new TreeSet<CSPVariable>(variables);
        for (CSPVariable variable: variables){
            possibleAssignments += variable.getDomain().size();
        }
        assessor = new Assessor();
    }

    /**
     * Explicitly set the Assessor's weights
     * @param variables A list of CSPVariables representing the shifts to be assigned.
     * @param weights a list of weights to be applied to the assessment functions. (must match number of funcs)
     */
    public CSPState(List<CSPVariable> variables, List<Double> weights) throws WeightException {
        this.variables = new TreeSet<CSPVariable>(variables);
        for (CSPVariable variable: variables){
            possibleAssignments += variable.getDomain().size();
        }
        assessor = new Assessor(weights);
    }

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
        // TODO: implement run
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

    public boolean isComplete() {return possibleAssignments == 0 && satisfiable;}

    public boolean isSatisfiable() {return satisfiable;}
}
