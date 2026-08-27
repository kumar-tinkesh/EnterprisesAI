"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { LogIn } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { dashboardPathForRole, loginSchema, type LoginValues } from "@/lib/validations";
import { useAuthStore } from "@/stores/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, FieldError } from "@/components/auth-fields";

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
      router.push(dashboardPathForRole(payload.user.role));
    },
  });

  const onSubmit = handleSubmit((values) => {
    clearErrors();
    mutation.mutate(values);
  });

  return (
    <div className="space-y-4">
      <GoogleButton />
      <div className="relative flex items-center justify-center">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-zinc-200" />
        </div>
        <span className="relative bg-white px-2 text-xs uppercase text-zinc-400">
          Or continue with
        </span>
      </div>
      <form onSubmit={onSubmit} className="space-y-4">
        <Field label="Email">
          <Input type="email" placeholder="you@company.com" {...register("email")} />
          <FieldError msg={formState.errors.email?.message} />
        </Field>
        <Field label="Password">
          <Input type="password" placeholder="••••••••" {...register("password")} />
          <FieldError msg={formState.errors.password?.message} />
        </Field>

        {mutation.isError && (
          <p className="text-xs text-red-600">
            {mutation.error instanceof ApiError
              ? mutation.error.message
              : "Failed to log in"}
          </p>
        )}

        <Button type="submit" disabled={mutation.isPending} className="w-full" size="lg">
          {mutation.isPending ? <Spinner /> : <LogIn />} Login
        </Button>
      </form>
    </div>
  );
}