import { Amplify } from "aws-amplify";

let configured = false;

export function configureAmplify() {
  if (configured) return;
  const userPoolEndpoint = process.env.NEXT_PUBLIC_COGNITO_ENDPOINT;
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
        userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!,
        ...(userPoolEndpoint ? { userPoolEndpoint } : {}),
        loginWith: { email: true },
        signUpVerificationMethod: "code",
      },
    },
  });
  configured = true;
}

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  NotAuthorizedException: "Incorrect email or password.",
  UserNotFoundException: "Incorrect email or password.",
  UsernameExistsException: "An account with this email already exists. Sign in instead.",
  InvalidPasswordException:
    "Password must be at least 8 characters and include an uppercase letter, a lowercase letter and a number.",
  CodeMismatchException: "That code doesn't match. Check the email and try again.",
  ExpiredCodeException: "That code has expired. Send a new one.",
  LimitExceededException: "Too many attempts. Wait a few minutes and try again.",
  TooManyRequestsException: "Too many attempts. Wait a few minutes and try again.",
  NetworkError: "Can't reach the sign-in service. Check your connection and try again.",
};

export function authErrorMessage(error: unknown): string {
  const name = error instanceof Error ? error.name : "";
  if (name in AUTH_ERROR_MESSAGES) return AUTH_ERROR_MESSAGES[name];
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Try again.";
}
