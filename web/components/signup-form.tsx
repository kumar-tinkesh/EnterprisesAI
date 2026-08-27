"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { UserPlus } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import {
  ROLES,
  dashboardPathForRole,
  signupSchema,
  type SignupValues,
} from "@/lib/validations";
import { useAuthStore } from "@/stores/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, FieldError } from "@/components/auth-fields";

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
      router.push(dashboardPathForRole(payload.user.role));
    },
  });

  const onSubmit = handleSubmit((values) => {
    clearErrors();
    mutation.mutate(values);
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Field label="Full name">
        <Input placeholder="Jane Doe" {...register("fullName")} />
        <FieldError msg={formState.errors.fullName?.message} />
      </Field>

      <Field label="Email">
        <Input type="email" placeholder="you@company.com" {...register("email")} />
        <FieldError msg={formState.errors.email?.message} />
      </Field>

      <Field label="Password">
        <Input type="password" placeholder="At least 8 characters" {...register("password")} />
        <FieldError msg={formState.errors.password?.message} />
      </Field>

      <Field label="Confirm password">
        <Input type="password" placeholder="Repeat password" {...register("confirmPassword")} />
        <FieldError msg={formState.errors.confirmPassword?.message} />
      </Field>

      {mutation.isError && (
        <p className="text-xs text-red-600">
          {mutation.error instanceof ApiError
            ? mutation.error.message
            : "Failed to create account"}
        </p>
      )}

      <Button type="submit" disabled={mutation.isPending} className="w-full" size="lg">
        {mutation.isPending ? <Spinner /> : <UserPlus />} Create account
      </Button>
    </form>
  );
}