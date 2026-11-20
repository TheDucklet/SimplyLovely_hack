import type { CurrentUser } from '../api/types';

const ROLE_NAMES: Record<string, string> = {
  entrepreneur: 'Предприниматель',
  credit_officer: 'Кредитный специалист',
  analyst: 'Аналитик',
  admin: 'Администратор',
};

function roleNames(roles: string[]): string {
  return roles.map((role) => ROLE_NAMES[role] ?? role).join(', ');
}

export function AccountMenu({ user }: { user: CurrentUser }) {
  if (user.mode !== 'oidc') return null;
  return (
    <div className="account-menu">
      <span className="account-name" title={roleNames(user.roles)}>
        {user.name || roleNames(user.roles)}
      </span>
      {user.logout_url && (
        <a className="account-logout" href={user.logout_url}>
          Выйти
        </a>
      )}
    </div>
  );
}
