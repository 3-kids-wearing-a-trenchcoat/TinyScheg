package CSP.Exceptions;

public class WeightException extends Exception{
    public WeightException () {
        super();
    }

    public WeightException (String message) {
        super (message);
    }

    public WeightException (Throwable cause) {
        super (cause);
    }

    public WeightException(String message, Throwable cause) {
        super (message, cause);
    }
}
