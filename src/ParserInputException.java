/**
 * Thrown by Parser to indicate bad input
 */
public class ParserInputException extends Exception {
        public ParserInputException () {
            super();
        }

        public ParserInputException (String message) {
            super (message);
        }

        public ParserInputException (Throwable cause) {
            super (cause);
        }

        public ParserInputException(String message, Throwable cause) {
            super (message, cause);
        }

}
