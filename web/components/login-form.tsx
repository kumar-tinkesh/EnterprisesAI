"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { api, ApiError } from "@/lib/api";
import { afterLoginPath } from "@/lib/after-login";
import { loginSchema, type LoginValues } from "@/lib/validations";
import { useAuthStore } from "@/stores/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, FieldError, FormError, OrDivider, PasswordInput } from "@/components/auth-fields";
import { GoogleButton } from "@/components/google-button";

export function LoginForm() {
  const router = useRouter();
  const loginStore = useAuthStore((s) => s.login);
  const { register, handleSubmit, formState, clearErrors } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const mutation = useMutation({
    mutationFn: api.login,
    onSuccess: (payload) => {
      loginStore(payload);
      router.push(afterLoginPath(payload.user.role));
    },
  });

  const onSubmit = handleSubmit((values) => {
    clearErrors();
    mutation.mutate(values);
  });

  return (
    <div className="space-y-5">
      <GoogleButton />
      <OrDivider />
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field label="Email">
          <Input type="email" autoComplete="email" inputMode="email" placeholder="you@company.com" {...register("email")} />
          <FieldError msg={formState.errors.email?.message} />
        </Field>
        <Field label="Password">
          <PasswordInput autoComplete="current-password" placeholder="Your password" {...register("password")} />
          <FieldError msg={formState.errors.password?.message} />
        </Field>

        {mutation.isError && (
          <FormError>
            {mutation.error instanceof ApiError ? mutation.error.message : "Couldn't log in. Try again."}
          </FormError>
        )}

        <Button type="submit" disabled={mutation.isPending} className="h-10 w-full">
          {mutation.isPending && <Spinner className="h-4 w-4" />} Log in
        </Button>
      </form>
    </div>
  );
}
