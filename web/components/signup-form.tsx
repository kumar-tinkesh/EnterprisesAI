"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { api, ApiError } from "@/lib/api";
import { afterLoginPath } from "@/lib/after-login";
import { ROLES, signupSchema, type SignupValues } from "@/lib/validations";
import { useAuthStore } from "@/stores/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, FieldError, FormError, OrDivider, PasswordInput } from "@/components/auth-fields";
import { GoogleButton } from "@/components/google-button";

export function SignupForm() {
  const router = useRouter();
  const loginStore = useAuthStore((s) => s.login);
  const { register, handleSubmit, formState, clearErrors } = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      email: "",
      password: "",
      confirmPassword: "",
      fullName: "",
      role: ROLES.soloUser,
      tenantName: "Personal",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: SignupValues) =>
      api.signup({
        email: values.email,
        password: values.password,
        full_name: values.fullName,
        role: ROLES.soloUser,
        tenant_name: "Personal",
      }),
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
        <Field label="Full name">
          <Input autoComplete="name" placeholder="Jane Doe" {...register("fullName")} />
          <FieldError msg={formState.errors.fullName?.message} />
        </Field>

        <Field label="Email">
          <Input type="email" autoComplete="email" inputMode="email" placeholder="you@company.com" {...register("email")} />
          <FieldError msg={formState.errors.email?.message} />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Password">
            <PasswordInput autoComplete="new-password" placeholder="8+ characters" {...register("password")} />
            <FieldError msg={formState.errors.password?.message} />
          </Field>
          <Field label="Confirm password">
            <PasswordInput autoComplete="new-password" placeholder="Same again" {...register("confirmPassword")} />
            <FieldError msg={formState.errors.confirmPassword?.message} />
          </Field>
        </div>

        {mutation.isError && (
          <FormError>
            {mutation.error instanceof ApiError ? mutation.error.message : "Couldn't create the account. Try again."}
          </FormError>
        )}

        <Button type="submit" disabled={mutation.isPending} className="h-10 w-full">
          {mutation.isPending && <Spinner className="h-4 w-4" />} Create account
        </Button>
      </form>
    </div>
  );
}
