package CSP.Exceptions;

public class VariableAssignmentException extends Exception{
    public VariableAssignmentException () {
        super();
    }

    public VariableAssignmentException (String message) {
        super (message);
    }

    public VariableAssignmentException (Throwable cause) {
        super (cause);
    }

    public VariableAssignmentException(String message, Throwable cause) {
        super (message, cause);
    }
}
